/* 书单页：过滤 + 卡片列表
 *
 * 布局与样式严格照抄 templates/orders.html：
 *  - 工具条 = orders.html 的 Filter & Search Toolbar
 *  - 列表项 = orders.html 的 order-card
 * 这里只负责生成 DOM 与数据绑定。
 */

(function () {
  'use strict';

  const T = window.PawreadI18n;
  const t = T.t;

  const libList = document.getElementById('libList');
  const searchInput = document.getElementById('searchInput');
  const toolbarSearch = document.getElementById('toolbarSearch');
  const stateFilters = document.getElementById('stateFilters');
  const paginationCountText = document.getElementById('paginationCountText');

  /** 全部书。 */
  let books = [];

  /** 当前过滤条件。 */
  const filter = {
    states: new Set(),
    keyword: '',
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

  /** 过滤按钮样式 —— 与 templates/orders.html 的 filter-btn 一致。
   *
   * 未选中态不填充背景，只靠 hover 变色；
   * 选中态是纯黑胶囊。
   */
  const CHIP_ACTIVE = 'bg-[#000000] text-white font-semibold shadow-sm';
  const CHIP_OFF = 'text-on-surface-variant hover:bg-pink-50/70 hover:text-black';

  /** 画过滤条 —— 与 orders.html 的 statusFilterGroup 一致（单排）。 */
  function renderFilters() {
    stateFilters.innerHTML = '';

    // 优先级 pill
    [0, 1, 2, 3].forEach(lv => {
      const n = books.filter(b => b.priority === lv).length;
      if (!n) return;
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `filter-btn px-space-md py-2 rounded-full font-label-lg text-label-lg transition-all whitespace-nowrap ${CHIP_OFF}`;
      chip.innerHTML = `${esc(prioLabel(lv))} (${n})`;
      chip.dataset.state = `prio:${lv}`;
      chip.addEventListener('click', () => {
        const k = `prio:${lv}`;
        if (filter.states.has(k)) filter.states.delete(k);
        else filter.states.add(k);
        renderFilters();
        render();
      });
      stateFilters.appendChild(chip);
    });

    // 状态 pill
    STATE_GROUPS.forEach((g) => {
      const n = books.filter(b => stateGroup(b.state) === g.key).length;
      if (!n) return;
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `filter-btn px-space-md py-2 rounded-full font-label-lg text-label-lg transition-all whitespace-nowrap ${CHIP_OFF}`;
      chip.innerHTML = `${esc(t(g.i18n))} (${n})`;
      chip.dataset.state = g.key;
      chip.addEventListener('click', () => {
        if (filter.states.has(g.key)) filter.states.delete(g.key);
        else filter.states.add(g.key);
        renderFilters();
        render();
      });
      stateFilters.appendChild(chip);
    });
  }

  /** 应用过滤。 */
  function visible() {
    return books.filter(b => {
      if (filter.states.size) {
        const ok = Array.from(filter.states).some(k => {
          if (k.startsWith('prio:')) return String(b.priority) === k.slice(5);
          return stateGroup(b.state) === k;
        });
        if (!ok) return false;
      }
      if (filter.keyword) {
        const kw = filter.keyword.toLowerCase();
        const hay = `${b.original_title || ''} ${b.display_title || ''}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }

  /** 状态胶囊 —— 与 orders.html 的状态胶囊一致。 */
  function statePill(b) {
    if (b.has_note) {
      return `<span class="px-space-sm py-0.5 rounded-full bg-emerald-50 border border-emerald-200/70 text-emerald-800 font-label-sm text-label-sm font-semibold flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span> ${esc(t('lib.hasNote'))}</span>`;
    }
    const s = b.state;
    if (s === 'unavailable') {
      const reason = (b.reasons && b.reasons[0] && b.reasons[0].detail) || '';
      return `<span class="px-space-sm py-0.5 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm font-medium flex items-center gap-1" title="${esc(reason)}"><span class="w-1.5 h-1.5 rounded-full bg-outline"></span> ${esc(t('state.unavailable'))}</span>`;
    }
    if (s === 'failed') {
      return `<span class="px-space-sm py-0.5 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm font-medium flex items-center gap-1" title="${esc(b.state_detail || '')}"><span class="w-1.5 h-1.5 rounded-full bg-outline"></span> ${esc(t('state.failed'))}</span>`;
    }
    if (s === 'pending') {
      return `<span class="px-space-sm py-0.5 rounded-full bg-pink-50 border border-pink-200/80 text-[#9d5b74] font-label-sm text-label-sm font-semibold">${esc(t('state.pending'))}</span>`;
    }
    if (s === 'noted') {
      return `<span class="px-space-sm py-0.5 rounded-full bg-emerald-50 border border-emerald-200/70 text-emerald-800 font-label-sm text-label-sm font-semibold flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-600"></span> ${esc(t('state.noted'))}</span>`;
    }
    return `<span class="px-space-sm py-0.5 rounded-full bg-pink-50 border border-pink-200/80 text-[#9d5b74] font-label-sm text-label-sm font-semibold">${esc(t('state.' + s) || s)}</span>`;
  }

  /** 渲染卡片列表 —— order-card 结构。 */
  function render() {
    const list = visible();

    if (!list.length) {
      libList.innerHTML = `
        <div class="p-space-lg rounded-lg bg-surface-container-lowest/80 backdrop-blur-2xl border border-pink-100/80 shadow-[0_12px_32px_-8px_rgba(244,162,140,0.08)]">
          <div class="text-center py-space-xl">
            <div class="w-12 h-12 mx-auto rounded-full bg-pink-50 border border-pink-200/60 flex items-center justify-center mb-space-md">
              <span class="material-symbols-outlined text-outline text-[24px]">filter_alt_off</span>
            </div>
            <div class="font-headline-sm text-headline-sm text-on-surface">${esc(t('lib.empty'))}</div>
          </div>
        </div>`;
      if (paginationCountText) {
        paginationCountText.innerHTML = `Showing <strong>0</strong> of <strong>${books.length}</strong> books`;
      }
      return;
    }

    libList.innerHTML = list.map(b => {
      // 原书名做主标题，当前语言的译名放元信息行
      const title = b.original_title || b.title?.text || b.display_title || '';
      const zh = b.display_title && b.display_title !== title ? b.display_title : '';

      // 标题行 pills：书名 + 优先级 + 状态（与 orders.html 的 title pills 一致）
      const prio = b.priority == null
        ? `<span class="px-space-xs py-0.5 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm font-semibold">${esc(t('lib.unranked'))}</span>`
        : `<span class="px-space-xs py-0.5 rounded-full bg-pink-50 border border-pink-200/80 text-[#9d5b74] font-label-sm text-label-sm font-semibold">${esc(prioLabel(b.priority))}</span>`;

      // 元信息行：编号 • 译名（与 orders.html 的 meta 行一致）
      // 作者放在右侧主位，meta 行不重复。
      const meta = [];
      if (b.id) meta.push(`<span class="font-mono text-[#9d5b74] font-medium">#${esc(b.id)}</span>`);
      if (zh) meta.push(`<span class="text-[#9d5b74] font-medium">${esc(zh)}</span>`);
      const metaHtml = meta.length
        ? meta.map((m, i) => (i ? '<span>•</span>' : '') + m).join('')
        : '';

      const iconCls = b.has_note
        ? 'bg-purple-100/70 border-purple-200/60 text-[#7a5980]'
        : 'bg-surface-container-highest border-zinc-200 text-on-surface-variant';
      const iconName = b.has_note ? 'menu_book' : 'hourglass_empty';

      // 右侧：主位 + 补充说明（与 orders.html 的右侧结构一致）
      // 主位放作者，补充说明放状态理由 —— 状态本身已经在标题行的胶囊里，不重复。
      const detail = b.state_detail || '';
      const sub = detail || b.license || b.source || '';

      return `
      <div class="order-card p-space-lg rounded-lg bg-surface-container-lowest/80 backdrop-blur-2xl border border-pink-100/80 shadow-[0_12px_32px_-8px_rgba(244,162,140,0.08)] hover:shadow-[0_18px_40px_-10px_rgba(244,162,140,0.16)] transition-all flex flex-col xl:flex-row xl:items-center justify-between gap-space-lg group"
           data-href="/read/${encodeURIComponent(b.id)}">
        <div class="flex items-start sm:items-center gap-space-md flex-wrap sm:flex-nowrap">
          <div class="w-12 h-12 rounded-full ${iconCls} flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
            <span class="material-symbols-outlined text-[24px]">${iconName}</span>
          </div>
          <div class="flex flex-col">
            <div class="flex items-center gap-space-xs flex-wrap">
              <span class="font-headline-sm text-headline-sm text-on-surface font-semibold">${esc(title)}</span>
              ${prio}
              ${statePill(b)}
            </div>
            <div class="flex items-center gap-space-sm mt-1 text-on-surface-variant font-label-md text-label-md flex-wrap">
              ${metaHtml}
            </div>
          </div>
        </div>
        <div class="flex items-center justify-between xl:justify-end gap-space-lg pt-space-sm xl:pt-0">
          <div class="flex flex-col text-left xl:text-right">
            <span class="font-headline-sm text-headline-sm text-on-surface font-bold">${esc(b.author || t('lib.unranked'))}</span>
            <span class="font-label-sm text-label-sm text-on-surface-variant">${esc(sub)}</span>
          </div>
          <div class="flex items-center gap-space-xs shrink-0 flex-wrap sm:flex-nowrap">
            <a class="px-space-md py-2 rounded-full bg-white/90 border border-pink-200/80 hover:bg-pink-50/50 text-on-surface font-label-md text-label-md transition-all flex items-center gap-1 shadow-sm"
               href="/read/${encodeURIComponent(b.id)}">
              <span class="material-symbols-outlined text-[16px] text-[#9d5b74]">download</span>
              <span class="hidden sm:inline">${esc(t('lib.read'))}</span>
            </a>
            <a class="px-space-md py-2 rounded-full bg-[#000000] text-white hover:bg-[#1f2937] font-label-md text-label-md transition-all flex items-center gap-1 shadow-sm"
               href="/read/${encodeURIComponent(b.id)}">
              <span>${esc(t('lib.read'))}</span>
              <span class="material-symbols-outlined text-[14px]">north_east</span>
            </a>
          </div>
        </div>
      </div>`;
    }).join('');

    libList.querySelectorAll('.order-card[data-href]').forEach(card => {
      card.addEventListener('click', ev => {
        if (ev.target.closest('a')) return;
        location.href = card.dataset.href;
      });
    });

    if (paginationCountText) {
      paginationCountText.innerHTML =
        `Showing <strong>${list.length}</strong> of <strong>${books.length}</strong> books`;
    }
  }

  /* ---------------------------------------------------------- 初始化 */

  /** 两个搜索框共用同一个关键词。 */
  function onSearch(val) {
    filter.keyword = val.trim();
    if (searchInput.value !== val) searchInput.value = val;
    if (toolbarSearch.value !== val) toolbarSearch.value = val;
    render();
  }

  searchInput.addEventListener('input', () => onSearch(searchInput.value));
  toolbarSearch.addEventListener('input', () => onSearch(toolbarSearch.value));

  const lang = T.getLang();
  api(`/api/books?lang=${encodeURIComponent(lang)}`)
    .then(data => {
      books = data.books || [];
      renderFilters();
      render();
    })
    .catch(e => {
      libList.innerHTML = `
        <div class="p-space-lg rounded-lg bg-surface-container-lowest/80 border border-pink-100/80">
          <div class="text-center py-space-xl font-body-md text-body-md text-on-surface-variant">${esc(e.message)}</div>
        </div>`;
    });
})();
