/**
 * 二游更新日历 — 前端逻辑（全自动版）
 * 数据流：index.html 内联 GAME_DATA → localStorage 合并 → 页面渲染
 * 定时任务通过 fetch_updates.py 自动更新 data.json 和 index.html
 */

const STORAGE_KEY = 'gacha_calendar';

// ===== 全局状态 =====
let appData = null;
let currentYear = 2026;
let currentMonth = 5;
let selectedDate = null;
let serverAvailable = false;

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', init);

function init() {
  loadFromStorage();
  renderAll();
  bindEvents();
  checkServerAvailability();
}

function loadFromStorage() {
  const stored = localStorage.getItem(STORAGE_KEY);

  if (!stored) {
    // 首次访问：从内联 GAME_DATA 加载
    appData = JSON.parse(JSON.stringify(GAME_DATA));
  } else {
    // 已有本地数据：以 GAME_DATA（定时任务更新后的权威数据）为准，
    // 保留用户在本地新增但尚未被定时任务收录的游戏
    const localData = JSON.parse(stored);
    const canonicalGames = JSON.parse(JSON.stringify(GAME_DATA.games));
    const canonicalIds = new Set(canonicalGames.map(g => g.id));

    // 用户新增的游戏（id 以 custom_ 开头且尚未被收录）
    const userOnlyGames = localData.games.filter(
      g => g.id.startsWith('custom_') && !canonicalIds.has(g.id)
    );

    appData = {
      games: [...canonicalGames, ...userOnlyGames],
      color_pool: GAME_DATA.color_pool,
      shape_pool: GAME_DATA.shape_pool
    };
  }
  saveToStorage();
}

function saveToStorage() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(appData));
}

function deleteGame(gameId, gameName) {
  if (confirm(`确定要删除「${gameName}」吗？\n该操作不可撤销，所有相关事件数据将被移除。`)) {
    appData.games = appData.games.filter(g => g.id !== gameId);
    saveToStorage();
    renderAll();
  }
}

// ===== 渲染 =====
function renderAll() {
  renderSidebar();
  renderCalendar();
}

// ===== 侧边栏 =====
function renderSidebar() {
  renderGameList();
  renderLegend();
}

function renderGameList() {
  const list = document.getElementById('game-list');
  list.innerHTML = '';

  appData.games.forEach((game, idx) => {
    const li = document.createElement('li');
    li.className = 'game-item' + (game.enabled ? '' : ' disabled');
    li.draggable = true;
    li.dataset.index = idx;
    li.dataset.gameId = game.id;

    // Checkbox
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'game-checkbox';
    cb.checked = game.enabled;
    cb.style.color = game.color;
    cb.addEventListener('change', (e) => {
      e.stopPropagation();
      game.enabled = cb.checked;
      li.classList.toggle('disabled', !game.enabled);
      saveToStorage();
      renderCalendar();
    });

    // Logo
    const logo = document.createElement('div');
    logo.className = 'game-logo';
    const shapeEl = document.createElement('div');
    shapeEl.className = `logo-${game.shape}`;
    shapeEl.style.color = game.color;
    shapeEl.style.background = (game.shape === 'diamond' || game.shape === 'hexagon' || game.shape === 'star' || game.shape === 'bolt' || game.shape === 'shield' || game.shape === 'leaf') ? game.color : 'transparent';
    logo.appendChild(shapeEl);

    // Name
    const name = document.createElement('span');
    name.className = 'game-name';
    name.textContent = game.name;

    // Drag handle
    const handle = document.createElement('span');
    handle.className = 'game-drag-handle';
    handle.textContent = '⋮⋮';

    li.append(cb, logo, name, handle);

    // Delete button
    const delBtn = document.createElement('span');
    delBtn.className = 'game-delete-btn';
    delBtn.textContent = '×';
    delBtn.title = '删除游戏';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteGame(game.id, game.name);
    });
    li.appendChild(delBtn);

    // Drag events
    li.addEventListener('dragstart', onDragStart);
    li.addEventListener('dragover', onDragOver);
    li.addEventListener('dragleave', onDragLeave);
    li.addEventListener('drop', onDrop);
    li.addEventListener('dragend', onDragEnd);

    list.appendChild(li);
  });
}

// ===== 拖拽排序 =====
let dragSrcIdx = null;

function onDragStart(e) {
  dragSrcIdx = parseInt(this.dataset.index);
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  this.classList.add('drag-over');
}

function onDragLeave() {
  this.classList.remove('drag-over');
}

function onDrop(e) {
  e.preventDefault();
  this.classList.remove('drag-over');
  const dstIdx = parseInt(this.dataset.index);
  if (dragSrcIdx !== null && dragSrcIdx !== dstIdx) {
    const [moved] = appData.games.splice(dragSrcIdx, 1);
    appData.games.splice(dstIdx, 0, moved);
    saveToStorage();
    renderSidebar();
    renderCalendar();
  }
}

function onDragEnd() {
  this.classList.remove('dragging');
  document.querySelectorAll('.game-item').forEach(el => el.classList.remove('drag-over'));
  dragSrcIdx = null;
}

// ===== 图例 =====
function renderLegend() {
  const typeLegend = document.getElementById('event-type-legend');
  const typeColors = {
    '前瞻': '#58a6ff',
    '版本更新': '#f0883e',
    '卡池': '#da3633'
  };
  typeLegend.innerHTML = Object.entries(typeColors).map(([type, color]) =>
    `<div class="event-type-item"><span class="event-type-badge" style="background:${color}">${type}</span></div>`
  ).join('');
}

// ===== 可用颜色/形状池计算 =====
function computeAvailablePools() {
  const usedColors = appData.games.map(g => g.color);
  const availableColors = (GAME_DATA.color_pool || []).filter(c => !usedColors.includes(c));
  const usedShapes = appData.games.map(g => g.shape);
  const availableShapes = (GAME_DATA.shape_pool || []).filter(s => !usedShapes.includes(s));
  return { availableColors, availableShapes };
}

// ===== 日历渲染 =====
function renderCalendar() {
  const grid = document.getElementById('calendar-grid');
  const title = document.getElementById('calendar-nav-title');

  const month1 = currentMonth;
  const year1 = currentYear;
  let month2 = month1 + 1;
  let year2 = year1;
  if (month2 > 12) { month2 = 1; year2++; }

  title.textContent = `${year1}年${month1}月 & ${year2}年${month2}月`;

  grid.innerHTML = '';
  grid.appendChild(buildMonthCard(year1, month1));
  grid.appendChild(buildMonthCard(year2, month2));

  updateDetailPanel();
}

function buildMonthCard(year, month) {
  const card = document.createElement('div');
  card.className = 'month-card';

  const header = document.createElement('div');
  header.className = 'month-header';
  header.textContent = `${year}年${month}月`;
  card.appendChild(header);

  const weekdays = document.createElement('div');
  weekdays.className = 'month-weekdays';
  ['日','一','二','三','四','五','六'].forEach(d => {
    const span = document.createElement('span');
    span.textContent = d;
    weekdays.appendChild(span);
  });
  card.appendChild(weekdays);

  const daysContainer = document.createElement('div');
  daysContainer.className = 'month-days';

  const firstDay = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;

  for (let i = 0; i < firstDay; i++) {
    const empty = document.createElement('div');
    empty.className = 'day-cell empty';
    daysContainer.appendChild(empty);
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const cell = document.createElement('div');
    cell.className = 'day-cell';
    const dateStr = `${year}-${String(month).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    cell.dataset.date = dateStr;

    if (dateStr === todayStr) cell.classList.add('today');

    const cellDate = new Date(year, month - 1, d);
    if (cellDate < new Date(today.getFullYear(), today.getMonth(), today.getDate())) {
      cell.classList.add('past');
    }

    const num = document.createElement('span');
    num.className = 'day-num';
    num.textContent = d;
    cell.appendChild(num);

    const eventsOnDay = getEventsForDate(dateStr);
    if (eventsOnDay.length > 0) {
      const dotsContainer = document.createElement('div');
      dotsContainer.className = 'day-events';
      const maxDots = 4;
      eventsOnDay.slice(0, maxDots).forEach(ev => {
        const game = appData.games.find(g => g.id === ev.gameId);
        if (!game || !game.enabled) return;
        const dot = document.createElement('span');
        dot.className = 'day-event-dot ' + (ev.event.confirmed ? 'confirmed' : 'estimated');
        dot.style.color = game.color;
        if (ev.event.confirmed) dot.style.background = game.color;
        dot.title = `${game.name}: ${ev.event.name}`;
        dotsContainer.appendChild(dot);
      });
      if (eventsOnDay.length > maxDots) {
        const more = document.createElement('span');
        more.className = 'day-more';
        more.textContent = `+${eventsOnDay.length - maxDots}`;
        dotsContainer.appendChild(more);
      }
      cell.appendChild(dotsContainer);
    }

    cell.addEventListener('click', () => {
      selectedDate = dateStr;
      document.querySelectorAll('.day-cell').forEach(el => { el.style.background = ''; el.style.borderColor = ''; });
      cell.style.background = 'rgba(88,166,255,0.12)';
      cell.style.borderColor = 'var(--accent)';
      updateDetailPanel();
    });

    daysContainer.appendChild(cell);
  }

  card.appendChild(daysContainer);
  return card;
}

function getEventsForDate(dateStr) {
  const result = [];
  appData.games.forEach(game => {
    if (!game.enabled) return;
    game.events.forEach(ev => {
      if (ev.date === dateStr) {
        result.push({ gameId: game.id, event: ev });
      }
    });
  });
  return result;
}

function getEventsForDateAll(dateStr) {
  const result = [];
  appData.games.forEach(game => {
    game.events.forEach(ev => {
      if (ev.date === dateStr) {
        result.push({ gameId: game.id, gameName: game.name, gameColor: game.color, event: ev });
      }
    });
  });
  return result;
}

// ===== 详情面板 =====
function updateDetailPanel() {
  const panel = document.getElementById('event-detail-panel');

  if (!selectedDate) {
    panel.innerHTML = '<p class="detail-placeholder">点击日历中的事件查看详情</p>';
    return;
  }

  const events = getEventsForDateAll(selectedDate);
  if (events.length === 0) {
    panel.innerHTML = `<p class="detail-placeholder">${selectedDate} — 暂无事件</p>`;
    return;
  }

  const typeColorMap = { '前瞻': '#58a6ff', '版本更新': '#f0883e', '卡池': '#da3633' };
  const list = document.createElement('ul');
  list.className = 'event-detail-list';

  events.forEach(item => {
    const li = document.createElement('li');
    li.className = 'event-detail-item';
    li.style.borderLeftColor = item.gameColor;

    const badge = document.createElement('span');
    badge.className = 'event-detail-badge';
    badge.style.background = typeColorMap[item.event.type] || item.gameColor;
    badge.textContent = item.event.type;

    const info = document.createElement('div');
    info.className = 'event-detail-info';

    const ename = document.createElement('div');
    ename.className = 'event-detail-name';
    ename.textContent = item.event.name;
    if (!item.event.confirmed) {
      ename.textContent += ' ⚠';
      ename.style.opacity = '0.7';
    }

    const desc = document.createElement('div');
    desc.className = 'event-detail-desc';
    desc.textContent = item.event.detail || '';

    const gameTag = document.createElement('div');
    gameTag.className = 'event-detail-game';
    const dot = document.createElement('span');
    dot.style.display = 'inline-block';
    dot.style.width = '8px';
    dot.style.height = '8px';
    dot.style.borderRadius = '50%';
    dot.style.background = item.event.confirmed ? item.gameColor : 'transparent';
    dot.style.border = item.event.confirmed ? 'none' : `1.5px dashed ${item.gameColor}`;
    dot.style.marginRight = '6px';
    gameTag.appendChild(dot);
    gameTag.appendChild(document.createTextNode(item.gameName + (item.event.confirmed ? ' · 已确认' : ' · 推算')));
    li.style.borderLeftColor = item.gameColor;

    info.append(ename, desc, gameTag);
    li.append(badge, info);
    li.addEventListener('click', () => showEventModal(item));
    list.appendChild(li);
  });

  panel.innerHTML = '';
  panel.appendChild(list);
}

// ===== 事件弹窗 =====
function showEventModal(item) {
  const overlay = document.getElementById('modal-event-overlay');
  const title = document.getElementById('modal-event-title');
  const body = document.getElementById('modal-event-body');

  title.textContent = item.event.name;
  body.innerHTML = `
    <div style="margin-bottom:12px">
      <span style="display:inline-block;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:600;color:#fff;background:${item.gameColor};margin-right:6px;">${item.gameName}</span>
      <span style="display:inline-block;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:600;color:#fff;background:${item.event.confirmed ? '#2ea043' : '#8b949e'};">${item.event.confirmed ? '已确认' : '推算'}</span>
    </div>
    <p style="color:var(--text-secondary);font-size:0.85rem;line-height:1.6;margin-bottom:8px;">📅 ${item.event.date}</p>
    <p style="color:var(--text-secondary);font-size:0.85rem;line-height:1.6;margin-bottom:8px;">🏷 ${item.event.type}</p>
    <p style="color:var(--text-secondary);font-size:0.85rem;line-height:1.6;">${item.event.detail || '暂无详细信息'}</p>
  `;

  overlay.classList.add('active');
}

// ===== GitHub Pages 仓库推断 =====
function getGitHubRepoUrl() {
  const host = window.location.hostname;
  const path = window.location.pathname;
  if (host.endsWith('github.io')) {
    const username = host.replace('.github.io', '');
    const parts = path.split('/').filter(Boolean);
    const repo = parts[0] || username + '.github.io';
    return `https://github.com/${username}/${repo}`;
  }
  return null;
}

// ===== 手动更新按钮 =====
let updateTimer = null;

function handleUpdate() {
  const repoUrl = getGitHubRepoUrl();
  if (repoUrl) {
    window.open(`${repoUrl}/actions/workflows/update.yml`, '_blank');
    return;
  }
  // 本地开发回退
  const btn = document.getElementById('btn-update');
  const icon = btn.querySelector('.btn-update-icon');
  const text = btn.querySelector('.btn-update-text');

  if (btn.classList.contains('loading')) return;
  if (updateTimer) clearTimeout(updateTimer);

  btn.classList.add('loading');
  icon.textContent = '↻';
  text.textContent = '更新中…';

  fetch('/api/update', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      btn.classList.remove('loading');
      if (data.success) {
        btn.classList.add('success');
        text.textContent = '更新完成';
        setTimeout(() => { location.reload(); }, 1500);
      } else {
        btn.classList.add('error');
        text.textContent = '更新失败';
        updateTimer = setTimeout(resetUpdateBtn, 4000);
      }
    })
    .catch(() => {
      btn.classList.remove('loading');
      btn.classList.add('error');
      text.textContent = '服务器未启动';
      updateTimer = setTimeout(resetUpdateBtn, 4000);
    });
}

function resetUpdateBtn() {
  const btn = document.getElementById('btn-update');
  const icon = btn.querySelector('.btn-update-icon');
  const text = btn.querySelector('.btn-update-text');
  btn.classList.remove('success', 'error');
  icon.textContent = '↻';
  text.textContent = '手动更新';
}

// ===== 事件绑定 =====
function bindEvents() {
  document.getElementById('btn-update').addEventListener('click', handleUpdate);

  document.getElementById('btn-prev').addEventListener('click', () => {
    currentMonth -= 2;
    normalizeMonth();
    renderCalendar();
  });
  document.getElementById('btn-next').addEventListener('click', () => {
    currentMonth += 2;
    normalizeMonth();
    renderCalendar();
  });
  document.getElementById('btn-today').addEventListener('click', () => {
    const now = new Date();
    currentYear = now.getFullYear();
    currentMonth = now.getMonth() + 1;
    renderCalendar();
  });

  const addBtn = document.getElementById('btn-add-game');
  const modalOverlay = document.getElementById('modal-overlay');
  const cancelBtn = document.getElementById('btn-cancel');
  const form = document.getElementById('form-add-game');
  const colorPicker = document.getElementById('color-picker');
  const shapePicker = document.getElementById('shape-picker');

  const { availableColors, availableShapes } = computeAvailablePools();
  let selectedColor = availableColors[0] || '#E91E63';
  let selectedShape = availableShapes[0] || 'hexagon';

  function updatePickerUI() {
    colorPicker.querySelectorAll('.color-swatch').forEach(el => {
      el.classList.toggle('selected', el.dataset.color === selectedColor);
    });
    shapePicker.querySelectorAll('.shape-option').forEach(el => {
      el.classList.toggle('selected', el.dataset.shape === selectedShape);
    });
  }

  function refreshPickers() {
    const pools = computeAvailablePools();
    colorPicker.querySelectorAll('.color-swatch').forEach(el => {
      const color = el.dataset.color;
      const available = pools.availableColors.includes(color);
      el.style.opacity = available ? '1' : '0.25';
      el.style.pointerEvents = available ? 'auto' : 'none';
    });
    shapePicker.querySelectorAll('.shape-option').forEach(el => {
      const shape = el.dataset.shape;
      const available = pools.availableShapes.includes(shape);
      el.style.opacity = available ? '1' : '0.25';
      el.style.pointerEvents = available ? 'auto' : 'none';
    });
    const pools2 = computeAvailablePools();
    if (!pools2.availableColors.includes(selectedColor)) {
      selectedColor = pools2.availableColors[0] || '#E91E63';
    }
    if (!pools2.availableShapes.includes(selectedShape)) {
      selectedShape = pools2.availableShapes[0] || 'hexagon';
    }
    updatePickerUI();
  }

  addBtn.addEventListener('click', () => {
    refreshPickers();
    modalOverlay.classList.add('active');
    document.getElementById('input-game-name').focus();
  });

  cancelBtn.addEventListener('click', () => {
    modalOverlay.classList.remove('active');
    form.reset();
  });
  modalOverlay.addEventListener('click', (e) => {
    if (e.target === modalOverlay) {
      modalOverlay.classList.remove('active');
      form.reset();
    }
  });

  colorPicker.addEventListener('click', (e) => {
    if (e.target.classList.contains('color-swatch')) {
      selectedColor = e.target.dataset.color;
      updatePickerUI();
    }
  });

  shapePicker.addEventListener('click', (e) => {
    if (e.target.classList.contains('shape-option')) {
      selectedShape = e.target.dataset.shape;
      updatePickerUI();
    }
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const name = document.getElementById('input-game-name').value.trim();
    const cycle = parseInt(document.getElementById('input-cycle').value);

    // 验证
    let valid = true;
    clearErrors();

    if (!name) {
      showError('input-game-name', '游戏名不能为空');
      valid = false;
    } else if (name.length < 2) {
      showError('input-game-name', '游戏名至少需要 2 个字符');
      valid = false;
    } else if (appData.games.some(g => g.name === name)) {
      showError('input-game-name', `「${name}」已存在，不能重复添加`);
      valid = false;
    }

    if (isNaN(cycle) || cycle < 1 || cycle > 365 || !Number.isInteger(cycle)) {
      showError('input-cycle', '版本周期必须为 1-365 的正整数');
      valid = false;
    }

    if (!valid) return;

    const newGame = {
      id: 'custom_' + Date.now(),
      name: name,
      color: selectedColor,
      shape: selectedShape,
      version_cycle_days: cycle,
      enabled: true,
      events: []
    };

    appData.games.push(newGame);
    saveToStorage();
    modalOverlay.classList.remove('active');
    form.reset();
    renderAll();

    showUpdateBanner(name);

    setTimeout(() => {
      const banner = document.getElementById('update-banner');
      if (banner && banner.classList.contains('active')) {
        banner.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 100);
  });

  const eventOverlay = document.getElementById('modal-event-overlay');
  document.getElementById('btn-event-close').addEventListener('click', () => {
    eventOverlay.classList.remove('active');
  });
  eventOverlay.addEventListener('click', (e) => {
    if (e.target === eventOverlay) eventOverlay.classList.remove('active');
  });

  // 实时名称验证
  const nameInput = document.getElementById('input-game-name');
  nameInput.addEventListener('input', () => {
    const val = nameInput.value.trim();
    if (val && appData.games.some(g => g.name === val)) {
      showError('input-game-name', `「${val}」已存在`);
    } else if (val && val.length < 2) {
      showError('input-game-name', '至少需要 2 个字符');
    } else {
      clearError('input-game-name');
    }
  });

  // 自动分析按钮
  const analyzeBtn = document.getElementById('btn-analyze');
  analyzeBtn.addEventListener('click', async () => {
    if (!serverAvailable) return;
    const name = document.getElementById('input-game-name').value.trim();
    if (!name || name.length < 2) return;

    analyzeBtn.disabled = true;
    analyzeBtn.textContent = '分析中…';

    try {
      const resp = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      const data = await resp.json();

      if (data.success && data.data) {
        const result = data.data;
        document.getElementById('input-cycle').value = result.cycle_days || 42;

        // 自动填充颜色
        if (result.color) {
          const swatch = document.querySelector(`.color-swatch[data-color="${result.color}"]`);
          if (swatch && swatch.style.opacity !== '0.25') {
            selectedColor = result.color;
            updatePickerUI();
          }
        }

        // 自动填充形状
        if (result.logo_shape) {
          const shapeOpt = document.querySelector(`.shape-option[data-shape="${result.logo_shape}"]`);
          if (shapeOpt && shapeOpt.style.opacity !== '0.25') {
            selectedShape = result.logo_shape;
            updatePickerUI();
          }
        }

        analyzeBtn.textContent = '✓ 分析完成';
        analyzeBtn.style.background = 'rgba(46,160,67,0.15)';
        analyzeBtn.style.borderColor = 'rgba(46,160,67,0.3)';
        analyzeBtn.style.color = '#2ea043';
        setTimeout(() => resetAnalyzeBtn(), 3000);
      } else {
        throw new Error(data.error || '分析失败');
      }
    } catch {
      analyzeBtn.textContent = '✕ 分析失败';
      analyzeBtn.style.background = 'rgba(218,54,51,0.12)';
      analyzeBtn.style.borderColor = 'rgba(218,54,51,0.3)';
      analyzeBtn.style.color = '#da3633';
      setTimeout(() => resetAnalyzeBtn(), 3000);
    }
  });

  function resetAnalyzeBtn() {
    const btn = document.getElementById('btn-analyze');
    btn.disabled = false;
    btn.textContent = '🔍 自动分析';
    btn.style.background = '';
    btn.style.borderColor = '';
    btn.style.color = '';
    updateAnalyzeButton();
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.getElementById('modal-overlay').classList.remove('active');
      document.getElementById('modal-event-overlay').classList.remove('active');
    }
    if (e.key === 'ArrowLeft' && !document.querySelector('.modal-overlay.active')) {
      currentMonth -= 2;
      normalizeMonth();
      renderCalendar();
    }
    if (e.key === 'ArrowRight' && !document.querySelector('.modal-overlay.active')) {
      currentMonth += 2;
      normalizeMonth();
      renderCalendar();
    }
  });
}

function normalizeMonth() {
  while (currentMonth < 1) { currentMonth += 12; currentYear--; }
  while (currentMonth > 12) { currentMonth -= 12; currentYear++; }
}

// ===== 横幅提示 =====
function showUpdateBanner(gameName) {
  const banner = document.getElementById('update-banner');
  if (!banner) return;

  banner.querySelector('.banner-text').textContent =
    `「${gameName}」已保存，系统将在下一次自动更新中搜集其更新日程`;
  banner.classList.add('active');

  setTimeout(() => {
    banner.classList.add('fading');
    setTimeout(() => {
      banner.classList.remove('active', 'fading');
    }, 600);
  }, 8000);

  banner.querySelector('.banner-close').onclick = () => {
    banner.classList.add('fading');
    setTimeout(() => {
      banner.classList.remove('active', 'fading');
    }, 600);
  };
}

// ===== 表单验证辅助 =====
const ERROR_MAP = {
  'input-game-name': 'error-name',
  'input-cycle': 'error-cycle'
};

function showError(inputId, message) {
  const input = document.getElementById(inputId);
  if (input) input.classList.add('input-error');
  const errorId = ERROR_MAP[inputId];
  if (errorId) {
    const span = document.getElementById(errorId);
    if (span) {
      span.textContent = message;
      span.classList.add('visible');
    }
  }
}

function clearError(inputId) {
  const input = document.getElementById(inputId);
  if (input) input.classList.remove('input-error');
  const errorId = ERROR_MAP[inputId];
  if (errorId) {
    const span = document.getElementById(errorId);
    if (span) {
      span.textContent = '';
      span.classList.remove('visible');
    }
  }
}

function clearErrors() {
  ['input-game-name', 'input-cycle'].forEach(id => clearError(id));
}

// ===== 服务器可用性检测 =====
async function checkServerAvailability() {
  // GitHub Pages 纯静态环境，无后端服务器
  if (window.location.hostname.endsWith('github.io')) {
    serverAvailable = false;
    updateAnalyzeButton();
    return;
  }
  try {
    await fetch('/', { method: 'GET' });
    serverAvailable = true;
  } catch {
    serverAvailable = false;
  }
  updateAnalyzeButton();
}

function updateAnalyzeButton() {
  const btn = document.getElementById('btn-analyze');
  if (!btn) return;
  const isGHPages = window.location.hostname.endsWith('github.io');
  if (serverAvailable) {
    btn.disabled = false;
    btn.title = '自动搜索分析版本周期';
    btn.style.opacity = '1';
    btn.style.cursor = 'pointer';
  } else {
    btn.disabled = true;
    btn.title = isGHPages ? '自动分析需在本地运行 server.py' : '需先启动 python server.py';
    btn.style.opacity = '0.4';
    btn.style.cursor = 'not-allowed';
  }
}