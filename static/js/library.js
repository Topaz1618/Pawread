/* 书单页：卡片列表 + 过滤 */

(function () {
  'use strict';

  const T = window.PawreadI18n;
  const t = T.t;

  const libList = document.getElementById('libList');
  const summary = document.getElementById('libSummary');
  const searchInput = document.getElementById('searchInput');
  const onlyNoted = document.getElementById('onlyNoted');
  const prioFilters = document.getElementById('prioFilters');
  const stateFilters = document.getElementById('stateFilters');

  /** 全部书。 */
  let books = [];

  /** 当前过滤条件。 */
  const filter = {
    priorities: new Set(),
    states: new Set(),
    keyword: '',
    onlyNoted: true,
  };

  /** 优先级显示名。 */
  function prioLabel(lv) { return t('prio.' + lv); }

  /** 状态分组。 */
  const STATE_GROUPS = [
    { key: 'noted', i18n: 'group.noted' },
    { key: 'active', i18n: 'group.active' },
    { key: 'unavailable', i18n: 'group.unavailable' },
    { key: 'failed', i18n: 'group.failed' },
    { key: 'pending', i18n: 'group.pending' },
  ];

  /** 判断状态属于哪一组。 */
  function stateGroup(state) {
    if (state === 'noted' || state === 'available') return 'noted';
    if (state === 'failed') return 'failed';
    if (state === 'unavailable') return 'unavailable';
    if (state === 'pending') return 'pending';
    return 'active';
  }

  /** 画优先级过滤条。 */
  function renderPrioFilters() {
    prioFilters.querySelectorAll('.chip').forEach(c => c.remove());
    [0, 1, 2, 3].forEach(lv => {
      const n = books.filter(b => b.priority === lv).length;
      if (!n) return;
      const chip = document.createElement('button');
      chip.className = 'chip';
      chip.innerHTML = `${esc(prioLabel(lv))}<span class="count">${n}</span>`;
      chip.dataset.prio = String(lv);
      chip.addEventListener('click', () => {
        const k = String(lv);
        if (filter.priorities.has(k)) filter.priorities.delete(k);
        else filter.priorities.add(k);
        chip.classList.toggle('on');
        render();
      });
      prioFilters.appendChild(chip);
    });
  }

  /** 画状态过滤条。 */
  function renderStateFilters() {
    stateFilters.querySelectorAll('.chip').forEach(c => c.remove());
    STATE_GROUPS.forEach((g, i) => {
      const n = books.filter(b => stateGroup(b.state) === g.key).length;
      if (!n) return;
      const chip = document.createElement('button');
      chip.className = 'chip' + (i % 2 ? ' lav' : '');
      chip.innerHTML = `${esc(t(g.i18n))}<span class="count">${n}</span>`;
      chip.dataset.state = g.key;
      chip.addEventListener('click', () => {
        if (filter.states.has(g.key)) filter.states.delete(g.key);
        else filter.states.add(g.key);
        chip.classList.toggle('on');
        render();
      });
      stateFilters.appendChild(chip);
    });
  }

  /** 应用过滤。 */
  function visible() {
    return books.filter(b => {
      if (filter.onlyNoted && !b.has_note) return false;
      if (filter.priorities.size &&
          !filter.priorities.has(String(b.priority))) return false;
      if (filter.states.size && !filter.states.has(stateGroup(b.state))) return false;
      if (filter.keyword) {
        const kw = filter.keyword.toLowerCase();
        const hay = `${b.title?.text || ''} ${b.display_title || ''}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }

  /** 状态标签。 */
  function statePill(b) {
    if (b.has_note) {
      return `<span class="pill pill-ok"><span class="dot"></span> ${esc(t('lib.hasNote'))}</span>`;
    }
    const s = b.state;
    if (s === 'unavailable') {
      const reason = (b.reasons && b.reasons[0] && b.reasons[0].detail) || '';
      return `<span class="pill pill-warn" title="${esc(reason)}">${esc(t('state.unavailable'))}</span>`;
    }
    if (s === 'failed') {
      return `<span class="pill pill-err" title="${esc(b.state_detail || '')}">${esc(t('state.failed'))}</span>`;
    }
    if (s === 'pending') {
      return `<span class="pill pill-mute">${esc(t('state.pending'))}</span>`;
    }
    return `<span class="pill pill-lav"><span class="dot"></span> ${esc(t('state.' + s) || s)}</span>`;
  }

  /** 渲染卡片列表。 */
  function render() {
    const list = visible();
    const noted = list.filter(b => b.has_note).length;
    summary.textContent = t('lib.summary', {
      shown: list.length, total: books.length, noted,
    });

    if (!list.length) {
      libList.innerHTML = `
        <div class="card card-pad">
          <div class="empty">
            <div class="empty-mark">
              <span class="material-symbols-outlined" style="font-size:28px">filter_alt_off</span>
            </div>
            <div class="t-body">${esc(t('lib.empty'))}</div>
          </div>
        </div>`;
      return;
    }

    libList.innerHTML = list.map(b => {
      // 原书名做主标题，当前语言的译名做副标题
      const title = b.original_title || b.title?.text || b.display_title || '';
      const zh = b.display_title && b.display_title !== title
        ? b.display_title : '';
      const prio = b.priority == null
        ? `<span class="pill pill-mute">${esc(t('lib.unranked'))}</span>`
        : `<span class="pill pill-rose">${esc(prioLabel(b.priority))}</span>`;
      const iconCls = b.has_note ? 'icon-lav' : 'icon-mute';
      const iconName = b.has_note ? 'menu_book' : 'hourglass_empty';
      const meta = [];
      if (zh) meta.push(esc(zh));
      if (b.author) meta.push(esc(b.author));
      if (b.source) meta.push(esc(b.source));
      const metaHtml = meta.length
        ? meta.map((m, i) => (i ? '<span class="sep">•</span>' : '') + `<span>${m}</span>`).join('')
        : '';
      return `
      <div class="list-card" data-href="/read/${encodeURIComponent(b.id)}">
        <div class="list-icon ${iconCls}">
          <span class="material-symbols-outlined" style="font-size:24px">${iconName}</span>
        </div>
        <div style="min-width:0;flex:1">
          <div class="list-title">${esc(title)}</div>
          <div class="list-meta">
            ${prio}
            ${statePill(b)}
            ${metaHtml ? '<span class="sep">•</span>' + metaHtml : ''}
          </div>
        </div>
        <div class="list-actions">
          ${b.has_note
            ? `<a class="btn btn-ghost btn-sm" href="/read/${encodeURIComponent(b.id)}">${esc(t('lib.read'))}</a>`
            : ''}
        </div>
      </div>`;
    }).join('');

    libList.querySelectorAll('.list-card[data-href]').forEach(card => {
      card.addEventListener('click', ev => {
        if (ev.target.closest('a')) return;
        location.href = card.dataset.href;
      });
    });
  }

  /* ---------------------------------------------------------- 初始化 */

  searchInput.addEventListener('input', () => {
    filter.keyword = searchInput.value.trim();
    render();
  });

  onlyNoted.addEventListener('change', () => {
    filter.onlyNoted = onlyNoted.checked;
    render();
  });

  const lang = T.getLang();
  api(`/api/books?lang=${encodeURIComponent(lang)}`)
    .then(data => {
      books = data.books || [];
      renderPrioFilters();
      renderStateFilters();
      render();
    })
    .catch(e => {
      libList.innerHTML = `<div class="card card-pad">
        <div class="empty"><div class="t-body">${esc(e.message)}</div></div></div>`;
    });
})();