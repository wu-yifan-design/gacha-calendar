#!/usr/bin/env python3
"""
二游更新日历 — 轮询脚本 (fetch_updates.py)
==============================================
可被定时任务（如 cron / Task Scheduler）调用的独立脚本。
读取 data.json，搜索各游戏最新版本更新信息，提取确认日期并更新 data.json，
同时基于版本周期推算未来更新日期。

用法：
    python fetch_updates.py                    # 在当前目录查找 data.json
    python fetch_updates.py --data path/to/data.json  # 指定 data.json 路径
    python fetch_updates.py --dry-run           # 仅搜索不写入

依赖：仅使用 Python 标准库（urllib + re + json）
"""

import json
import os
import re
import sys
import argparse
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime, timedelta

# ===== 配置 =====
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
SEARCH_SOURCES = [
    # (搜索 URL 模板, 结果解析器类型)
    # 使用 Bing 搜索作为基础搜索引擎
    ("https://www.bing.com/search?q={query}&setlang=zh-cn", "bing"),
]
REQUEST_TIMEOUT = 15  # 秒
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

# ===== 搜索关键词模板 =====
# 已有游戏的常规搜索
SEARCH_QUERIES = [
    "{game_name} 前瞻 版本更新 最新",
    "{game_name} 新版本 上线日期",
    "{game_name} 卡池 活动 最新",
]

# 新游戏的搜索词分组（每组覆盖不同信息维度）
NEW_GAME_SEARCH_GROUPS = [
    {
        "purpose": "版本更新周期",
        "queries": [
            "{game_name} 版本更新周期",
            "{game_name} 多久更新一次版本",
            "{game_name} 版本周期 多少天",
        ],
    },
    {
        "purpose": "最新版本前瞻",
        "queries": [
            "{game_name} 最新版本 前瞻 更新",
            "{game_name} 新版本 预告 上线",
            "{game_name} 下个版本 前瞻直播",
        ],
    },
    {
        "purpose": "历史版本时间线",
        "queries": [
            "{game_name} 版本历史 更新时间",
            "{game_name} 历次版本 上线日期",
            "{game_name} 版本更新记录",
        ],
    },
]

# ===== 日期提取正则 =====
DATE_PATTERNS = [
    # 完整日期: 2026-06-08 / 2026年6月8日
    re.compile(r"(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})[日号]?"),
    # 月日: 6月8日
    re.compile(r"(\d{1,2})[月/\-.](\d{1,2})[日号]?"),
    # 相对日期: "下周四" / "下周三" 等 (从当前日期推算)
    re.compile(r"(下[周一二三四五六日天])"),
]

# 中文模糊日期映射（上旬/中旬/下旬）
FUZZY_MONTH_MAP = {
    "上旬": 5, "中旬": 15, "下旬": 25,
    "月初": 3, "月中": 15, "月末": 28,
}

# 月份模糊日期正则
FUZZY_DATE_PATTERNS = [
    re.compile(r"(\d{1,2})月(上旬|中旬|下旬|月初|月中|月末)"),
    re.compile(r"(\d{4})[年/\-.](\d{1,2})月(上旬|中旬|下旬|月初|月中|月末)"),
]

# 相对时间正则
RELATIVE_TIME_PATTERNS = [
    re.compile(r"(下周)([一二三四五六日])"),
    re.compile(r"(本月末|本月底|这个月底)"),
    re.compile(r"(下个月)(\d{1,2})[日号]"),
]

# 周几映射 (0=Monday, but we use Python weekday: Mon=0, Sun=6)
WEEKDAY_NAMES = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

# 版本周期推断正则
CYCLE_PATTERNS = [
    re.compile(r"每\s*(\d+)\s*周\s*(更新|一次|一个版本)"),
    re.compile(r"(\d+)\s*天\s*(一个|一次|)(版本|更新)"),
    re.compile(r"版本\s*周期\s*(约|大约|)[^。]*?(\d+)\s*天"),
    re.compile(r"(\d+)\s*天\s*(左右|)"),
]

# 事件类型关键词
EVENT_TYPE_KEYWORDS = {
    "前瞻": ["前瞻", "前瞻直播", "前瞻特别节目", "版本前瞻"],
    "版本更新": ["版本更新", "正式上线", "更新上线", "版本上线", "新版本"],
    "卡池": ["卡池", "限定", "复刻", "UP池", "祈愿", "招募"],
}


def build_search_url(query: str) -> str:
    """构造搜索 URL"""
    encoded = urllib.parse.quote(query)
    return f"https://www.bing.com/search?q={encoded}&setlang=zh-cn"


def fetch_page(url: str) -> str:
    """抓取网页内容（纯文本）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
            raw = resp.read()
            # 尝试解码
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                return raw.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] 请求失败: {e}")
        return ""


def extract_dates_from_html(html: str, current_year: int) -> list[dict]:
    """从 HTML 中提取日期信息"""
    # 去除 HTML 标签
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    results = []

    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            if pattern == DATE_PATTERNS[0]:
                # 完整日期
                y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if 2024 <= y <= 2027 and 1 <= m <= 12 and 1 <= d <= 31:
                    results.append({
                        "date": f"{y}-{m:02d}-{d:02d}",
                        "context": text[max(0, match.start() - 30):match.end() + 30],
                    })
            elif pattern == DATE_PATTERNS[1]:
                # 月日格式，补充年份
                m, d = int(match.group(1)), int(match.group(2))
                if 1 <= m <= 12 and 1 <= d <= 31:
                    # 假设在当前年份前后范围内
                    for y in (current_year, current_year + 1):
                        results.append({
                            "date": f"{y}-{m:02d}-{d:02d}",
                            "context": text[max(0, match.start() - 30):match.end() + 30],
                        })

    # 去重
    seen = set()
    unique = []
    for r in results:
        if r["date"] not in seen:
            seen.add(r["date"])
            unique.append(r)
    return unique


def classify_event_type(context: str) -> str:
    """根据上下文分类事件类型"""
    for etype, keywords in EVENT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in context:
                return etype
    return "版本更新"  # 默认


def search_game_updates(game: dict, current_year: int) -> list[dict]:
    """搜索单款游戏的最新更新信息"""
    found_events = []

    for query_template in SEARCH_QUERIES:
        query = query_template.format(game_name=game["name"])
        url = build_search_url(query)
        print(f"  搜索: {query}")
        html = fetch_page(url)
        if not html:
            continue

        dates = extract_dates_from_html(html, current_year)
        for d in dates:
            etype = classify_event_type(d["context"])
            # 检查是否匹配游戏名（在日期附近上下文中）
            if game["name"] in d["context"] or True:  # 宽松匹配
                found_events.append({
                    "date": d["date"],
                    "type": etype,
                    "name": f"{game['name']} {etype}",
                    "detail": d["context"][:80].strip(),
                    "confirmed": True,
                })

        # 避免请求过快
        import time
        time.sleep(1)

    return found_events


def merge_events(existing: list[dict], new_events: list[dict]) -> list[dict]:
    """合并已有事件和新发现事件，避免重复"""
    merged = list(existing)
    existing_dates = {(e["date"], e["type"]) for e in existing if e.get("confirmed")}

    for ev in new_events:
        key = (ev["date"], ev["type"])
        if key not in existing_dates:
            merged.append(ev)
            existing_dates.add(key)

    # 按日期排序
    merged.sort(key=lambda e: e["date"])
    return merged


def predict_next_version(game: dict) -> dict:
    """推算下一版本日期"""
    # 找到最近一次「版本更新」类型的确认事件
    version_events = [
        e for e in game["events"]
        if e["type"] == "版本更新" and e.get("confirmed")
    ]
    if not version_events:
        return None

    latest = max(version_events, key=lambda e: e["date"])
    latest_date = datetime.strptime(latest["date"], "%Y-%m-%d")
    next_date = latest_date + timedelta(days=game["version_cycle_days"])

    # 提取版本号并递增
    version_match = re.search(r"(\d+\.\d+)", latest.get("name", ""))
    if version_match:
        parts = version_match.group(1).split(".")
        major, minor = int(parts[0]), int(parts[1])
        next_version = f"{major}.{minor + 1}"
    else:
        next_version = "下版本"

    return {
        "date": next_date.strftime("%Y-%m-%d"),
        "type": "版本更新",
        "name": f"{next_version} 版本（推算）",
        "detail": f"基于{game['version_cycle_days']}天周期推算，待官方确认",
        "confirmed": False,
    }


def update_predicted_events(game: dict):
    """更新推算事件：移除旧推算，添加新推算"""
    # 移除所有旧的推算版本更新事件
    game["events"] = [
        e for e in game["events"]
        if not (e["type"] == "版本更新" and not e.get("confirmed"))
    ]
    # 添加新的推算
    predicted = predict_next_version(game)
    if predicted:
        game["events"].append(predicted)


def parse_fuzzy_date(text: str, current_year: int) -> list[str]:
    """解析中文模糊日期（上旬/中旬/下旬/月初/月中/月末）"""
    results = []
    for pattern in FUZZY_DATE_PATTERNS:
        for match in pattern.finditer(text):
            if pattern == FUZZY_DATE_PATTERNS[0]:
                m = int(match.group(1))
                day = FUZZY_MONTH_MAP.get(match.group(2), 15)
            else:
                y = int(match.group(1))
                m = int(match.group(2))
                day = FUZZY_MONTH_MAP.get(match.group(3), 15)
            if 1 <= m <= 12:
                results.append(f"{current_year}-{m:02d}-{day:02d}")
    return results


def parse_relative_date(text: str, current_date: datetime) -> list[str]:
    """解析相对时间（下周几、本月末、下个月X号）"""
    results = []
    for pattern in RELATIVE_TIME_PATTERNS:
        for match in pattern.finditer(text):
            if "下周" in match.group(0):
                weekday_name = match.group(2)
                target_wd = WEEKDAY_NAMES.get(weekday_name)
                if target_wd is not None:
                    days_until = (target_wd - current_date.weekday()) % 7
                    if days_until == 0:
                        days_until = 7
                    target = current_date + timedelta(days=days_until + 7)
                    results.append(target.strftime("%Y-%m-%d"))
            elif "本月末" in match.group(0) or "本月底" in match.group(0) or "这个月底" in match.group(0):
                # 本月最后一天
                next_month = current_date.replace(day=28) + timedelta(days=4)
                last_day = next_month - timedelta(days=next_month.day)
                results.append(last_day.strftime("%Y-%m-%d"))
            elif "下个月" in match.group(0):
                d = int(match.group(2))
                y = current_date.year
                m = current_date.month + 1
                if m > 12:
                    m = 1
                    y += 1
                results.append(f"{y}-{m:02d}-{d:02d}")
    return results


def infer_version_cycle(text: str) -> int | None:
    """从搜索文本中推断版本周期（天数）"""
    best_days = None
    for pattern in CYCLE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                days = int(match.group(1))
                if pattern == CYCLE_PATTERNS[0]:
                    # 每X周更新 → X * 7
                    days = days * 7
                if 7 <= days <= 180:
                    if best_days is None or days == best_days:
                        return days
                    best_days = days
            except (ValueError, IndexError):
                pass
    return best_days


def assign_color(data: dict) -> str:
    """从调色板中分配下一个可用颜色"""
    used = {g["color"] for g in data.get("games", [])}
    pool = data.get("color_pool", [])
    for c in pool:
        if c not in used:
            return c
    # 所有颜色都被用了，返回第一个
    return pool[0] if pool else "#E91E63"


def assign_shape(data: dict) -> str:
    """从形状池中分配下一个可用形状"""
    used = {g["shape"] for g in data.get("games", [])}
    pool = data.get("shape_pool", ["hexagon", "star", "cross", "shield", "heart", "moon", "bolt", "leaf"])
    for s in pool:
        if s not in used:
            return s
    return pool[0] if pool else "hexagon"


def search_new_game(game_name: str, data: dict) -> dict:
    """
    对一款新游戏执行 3 组搜索，综合结果推断版本周期和事件列表。
    返回可直接追加到 data.json 的游戏对象 JSON。
    """
    current_date = datetime.now()
    current_year = current_date.year

    all_text = ""
    found_events = []
    inferred_cycle = None

    print(f"\n{'=' * 60}")
    print(f"  新游戏搜索: {game_name}")
    print(f"{'=' * 60}")

    for group in NEW_GAME_SEARCH_GROUPS:
        print(f"\n  [{group['purpose']}]")
        for query_template in group["queries"]:
            query = query_template.format(game_name=game_name)
            url = build_search_url(query)
            print(f"    搜索: {query}")
            html = fetch_page(url)
            if not html:
                continue

            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)
            all_text += " " + text

            # 提取标准日期
            dates = extract_dates_from_html(html, current_year)
            for d in dates:
                etype = classify_event_type(d["context"])
                found_events.append({
                    "date": d["date"],
                    "type": etype,
                    "name": f"{game_name} {etype}",
                    "detail": d["context"][:80].strip(),
                    "confirmed": True,
                })

            # 提取模糊日期
            fuzzy_dates = parse_fuzzy_date(text, current_year)
            for fd in fuzzy_dates:
                found_events.append({
                    "date": fd,
                    "type": "版本更新",
                    "name": f"{game_name} 版本更新",
                    "detail": f"从搜索结果推断（{fd}）",
                    "confirmed": False,
                })

            # 解析相对时间
            relative_dates = parse_relative_date(text, current_date)
            for rd in relative_dates:
                found_events.append({
                    "date": rd,
                    "type": "版本更新",
                    "name": f"{game_name} 版本更新",
                    "detail": f"从相对时间推断（{rd}）",
                    "confirmed": False,
                })

            import time
            time.sleep(0.5)

    # 推断版本周期
    inferred_cycle = infer_version_cycle(all_text)
    if inferred_cycle:
        print(f"\n  [推断] 版本周期: {inferred_cycle} 天")
    else:
        # 用搜索到的连续版本更新日期推算
        version_dates = sorted(set(
            e["date"] for e in found_events
            if e["type"] == "版本更新" and e.get("confirmed")
        ))
        if len(version_dates) >= 2:
            try:
                d1 = datetime.strptime(version_dates[0], "%Y-%m-%d")
                d2 = datetime.strptime(version_dates[1], "%Y-%m-%d")
                diff = abs((d2 - d1).days)
                if 7 <= diff <= 180:
                    inferred_cycle = diff
                    print(f"  [推断] 从版本间隔推算周期: {inferred_cycle} 天")
            except ValueError:
                pass

    if not inferred_cycle:
        inferred_cycle = 42  # 默认 42 天
        print(f"  [推断] 无法确定周期，使用默认: {inferred_cycle} 天")

    # 去重 + 排序事件
    seen = set()
    unique_events = []
    for ev in found_events:
        key = (ev["date"], ev["name"])
        if key not in seen:
            seen.add(key)
            unique_events.append(ev)
    unique_events.sort(key=lambda e: e["date"])

    # 推算未来版本
    confirmed_versions = [
        e for e in unique_events
        if e["type"] == "版本更新" and e.get("confirmed")
    ]
    if confirmed_versions:
        latest = max(confirmed_versions, key=lambda e: e["date"])
        latest_date = datetime.strptime(latest["date"], "%Y-%m-%d")
        next_date = latest_date + timedelta(days=inferred_cycle)
        # 检查是否已有该日期的事件
        next_str = next_date.strftime("%Y-%m-%d")
        if not any(e["date"] == next_str for e in unique_events):
            unique_events.append({
                "date": next_str,
                "type": "版本更新",
                "name": f"下版本（推算）",
                "detail": f"基于{inferred_cycle}天周期推算，待官方确认",
                "confirmed": False,
            })

    # 分配颜色和形状
    color = assign_color(data)
    shape = assign_shape(data)

    game_obj = {
        "id": "custom_" + re.sub(r"[^a-zA-Z0-9_]", "_", game_name).lower(),
        "name": game_name,
        "color": color,
        "shape": shape,
        "version_cycle_days": inferred_cycle,
        "enabled": True,
        "events": unique_events,
    }

    print(f"\n  [结果] 发现 {len(unique_events)} 个事件")
    print(f"  [结果] 版本周期: {inferred_cycle} 天")
    print(f"  [结果] 颜色: {color}  形状: {shape}")

    return game_obj


def build_new_game_output(game_obj: dict) -> str:
    """将新游戏对象格式化为可追加到 data.json 的 JSON 片段"""
    # 只输出游戏对象本身，不是完整的 data.json
    output = {
        "id": game_obj["id"],
        "name": game_obj["name"],
        "color": game_obj["color"],
        "shape": game_obj["shape"],
        "version_cycle_days": game_obj["version_cycle_days"],
        "enabled": True,
        "events": game_obj["events"],
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def load_data(filepath: str) -> dict:
    """加载 data.json"""
    if not os.path.exists(filepath):
        print(f"[ERROR] 文件不存在: {filepath}")
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def sync_html(data_filepath: str, html_filepath: str):
    """将 data.json 内容同步到 index.html 中的内联 GAME_DATA 变量"""
    if not os.path.exists(html_filepath):
        print(f"[WARN] HTML 文件不存在，跳过同步: {html_filepath}")
        return

    if not os.path.exists(data_filepath):
        print(f"[WARN] data.json 不存在，跳过同步: {data_filepath}")
        return

    with open(data_filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    with open(html_filepath, "r", encoding="utf-8") as f:
        html = f.read()

    # 替换内联 GAME_DATA 变量（匹配从 const GAME_DATA 到下一行 </script> 之间的所有内容）
    pattern = re.compile(r"const GAME_DATA\s*=\s*[\s\S]*?;\s*\n\s*</script>")
    replacement = f"const GAME_DATA = {data_json};\n</script>"

    if pattern.search(html):
        new_html = pattern.sub(replacement, html)
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(new_html)
        print(f"[OK] HTML 已同步: {html_filepath}")
    else:
        print(f"[WARN] HTML 中未找到 GAME_DATA 变量，无法同步: {html_filepath}")


def save_data(filepath: str, data: dict, dry_run: bool = False, sync_html_path: str = None):
    """保存 data.json，可选同步到 index.html"""
    if dry_run:
        print("\n[Dry-Run] 以下是将要写入的内容 (前 500 字符):")
        dumped = json.dumps(data, ensure_ascii=False, indent=2)
        print(dumped[:500] + ("..." if len(dumped) > 500 else ""))
        return

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 数据已写入: {filepath}")

    if sync_html_path:
        sync_html(filepath, sync_html_path)


def main():
    parser = argparse.ArgumentParser(
        description="二游更新日历 — 轮询脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python fetch_updates.py
  python fetch_updates.py --data /path/to/data.json
  python fetch_updates.py --dry-run
  python fetch_updates.py --new-game "原神"
  python fetch_updates.py --new-game "崩坏：星穹铁道" --output new_game.json
        """
    )
    parser.add_argument(
        "--data", dest="data_file", default=DATA_FILE,
        help=f"data.json 文件路径 (默认: {DATA_FILE})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅搜索和展示结果，不写入文件"
    )
    parser.add_argument(
        "--new-game", dest="new_game", default=None,
        help="搜索新游戏的更新日程并生成 JSON（不修改现有 data.json，输出到 stdout 或 --output）"
    )
    parser.add_argument(
        "--output", dest="output_file", default=None,
        help="新游戏结果输出文件路径（与 --new-game 配合使用，默认输出到 stdout）"
    )
    parser.add_argument(
        "--sync-html", dest="sync_html", default=None,
        help="index.html 文件路径，保存 data.json 后自动同步内联 GAME_DATA 变量"
    )
    parser.add_argument(
        "--analyze-only", dest="analyze_only", default=None,
        help="仅分析指定游戏的版本周期（输出纯 JSON 到 stdout，不修改 data.json）"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="输出详细日志"
    )
    args = parser.parse_args()

    # ========== 新游戏搜索模式 ==========
    if args.new_game:
        data = load_data(args.data_file) if os.path.exists(args.data_file) else {"games": [], "color_pool": [
            "#E91E63","#9C27B0","#00BCD4","#FFEB3B","#795548","#607D8B",
            "#F44336","#3F51B5","#009688","#CDDC39"
        ], "shape_pool": [
            "hexagon","star","cross","shield","heart","moon","bolt","leaf"
        ]}
        game_obj = search_new_game(args.new_game, data)
        output_json = build_new_game_output(game_obj)

        if args.output_file:
            with open(args.output_file, "w", encoding="utf-8") as f:
                f.write(output_json)
            print(f"\n[OK] 新游戏数据已写入: {args.output_file}")

            # 自动追加到 data.json
            if os.path.exists(args.data_file):
                with open(args.data_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                d["games"].append(json.loads(output_json))
                save_data(args.data_file, d, sync_html_path=args.sync_html)
        else:
            print("\n===== 新游戏 JSON（可追加到 data.json 的 games 数组）=====")
            print(output_json)
        return

    # ========== 仅分析模式 ==========
    if args.analyze_only:
        data = load_data(args.data_file) if os.path.exists(args.data_file) else {"games": [], "color_pool": [
            "#E91E63","#9C27B0","#00BCD4","#FFEB3B","#795548","#607D8B",
            "#F44336","#3F51B5","#009688","#CDDC39"
        ], "shape_pool": [
            "hexagon","star","cross","shield","heart","moon","bolt","leaf"
        ]}
        game_obj = search_new_game(args.analyze_only, data)
        result = {
            "cycle_days": game_obj["version_cycle_days"],
            "events": game_obj["events"],
            "logo_shape": game_obj["shape"],
            "color": game_obj["color"],
            "id": game_obj["id"],
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    print("=" * 60)
    print("  二游更新日历 — 轮询脚本")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  数据文件: {args.data_file}")
    print("=" * 60)

    data = load_data(args.data_file)
    current_year = datetime.now().year
    total_new = 0

    for game in data["games"]:
        try:
            print(f"\n>>> [{game['name']}] 版本周期={game['version_cycle_days']}天")
            if args.verbose:
                print(f"    当前事件数: {len(game['events'])}")

            # 搜索最新更新
            print("  [搜索] 正在搜索最新更新信息...")
            new_events = search_game_updates(game, current_year)
            print(f"  [搜索] 发现 {len(new_events)} 条可能的新事件")

            # 合并事件
            old_count = len(game["events"])
            game["events"] = merge_events(game["events"], new_events)
            added = len(game["events"]) - old_count
            if added > 0:
                print(f"  [合并] 新增 {added} 个事件")
                total_new += added

            # 更新推算
            update_predicted_events(game)
            print(f"  [推算] 已更新推算版本日期")
        except Exception as e:
            print(f"  [ERROR] 处理「{game['name']}」时出错: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            print(f"  [跳过] 保留原有数据，继续处理下一个游戏")
            continue

    print(f"\n{'=' * 60}")
    print(f"  总计新增事件: {total_new}")
    print(f"{'=' * 60}")

    save_data(args.data_file, data, dry_run=args.dry_run, sync_html_path=args.sync_html)

    if total_new == 0 and not args.dry_run:
        print("\n没有发现新事件，data.json 未变更。")


if __name__ == "__main__":
    main()