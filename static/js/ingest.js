/* 操作页：提交书单 + 实时队列 + 任务过滤
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

  const input = document.getElementById('titleInput');
  const submitBtn = document.getElementById('submitBtn');
  const countHint = document.getElementById('countHint');
  const queueList = document.getElementById('queueList');
  const queueFilters = document.getElementById('queueFilters');
  const queueSearch = document.getElementById('queueSearch');
  const paginationCountText = document.getElementById('paginationCountText');

  /** 当前任务表：id → job。 */
  const jobs = new Map();

  /** 任务过滤条件。 */
  const filter = {
    states: new Set(),
    keyword: '',
  };

  /** 过滤分组 —— 与书单页的分组一致。 */
  const STATE_GROUPS = [
    { key: 'all',         i18n: 'group.all' },
    { key: 'active',      i18n: 'group.active' },
    { key: 'noted',       i18n: 'group.noted' },
    { key: 'unavailable', i18n: 'group.unavailable' },
    { key: 'failed',      i18n: 'group.failed' },
    { key: 'pending',     i18n: 'group.pending' },
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

  /** 解析输入框里的书名。 */
  function parseTitles() {
    return input.value
      .split('\n')
      .map(s => s.trim())
      .filter(s => s.length > 0);
  }

  /** 更新计数与按钮状态。
   *
   * 按钮外观始终是纯黑（不因空输入降透明度），
   * 空输入时点击由下面的 `if (!titles.length) return;` 拦下。
   */
  function updateCount() {
    const n = parseTitles().length;
    countHint.textContent = t('ingest.count', { n });
    submitBtn.disabled = n === 0;
  }

  /** 状态 → 图标与配色（order-card 左侧圆形图标）。 */
  const STATE_STYLE = {
    noted:       { icon: 'task_alt',      circle: 'bg-purple-100/70 border-purple-200/60', text: 'text-[#7a5980]' },
    available:   { icon: 'auto_awesome',  circle: 'bg-pink-100/70 border-pink-200/60',   text: 'text-[#9d5b74]' },
    failed:      { icon: 'restart_alt',   circle: 'bg-surface-container-highest border-zinc-200', text: 'text-on-surface-variant' },
    unavailable: { icon: 'block',         circle: 'bg-surface-container-highest border-zinc-200', text: 'text-on-surface-variant' },
    pending:     { icon: 'schedule',      circle: 'bg-pink-100/70 border-pink-200/60',   text: 'text-[#9d5b74]' },
  };
  const ACTIVE_STATES = ['searching', 'downloading', 'verifying', 'noting'];

  /** 状态 → 状态胶囊（order-card 标题行第三个 pill）。 */
  const STATE_PILL = {
    noted:       'bg-emerald-50 border-emerald-200/70 text-emerald-800 font-semibold',
    available:   'bg-pink-50 border-pink-200/80 text-[#9d5b74] font-semibold',
    failed:      'bg-surface-container-high text-on-surface-variant font-medium',
    unavailable: 'bg-surface-container-high text-on-surface-variant font-medium',
    pending:     'bg-pink-50 border-pink-200/80 text-[#9d5b74] font-semibold',
  };

  /** 状态 → 圆点颜色。 */
  const STATE_DOT = {
    noted:       'bg-emerald-600',
    available:   'bg-[#9d5b74]',
    failed:      'bg-outline',
    unavailable: 'bg-outline',
    pending:     'bg-[#9d5b74]',
  };

  /** 画过滤条 —— 与 orders.html 的 statusFilterGroup 一致。 */
  function renderFilters() {
    if (!queueFilters) return;
    const all = Array.from(jobs.values());
    queueFilters.innerHTML = '';
    STATE_GROUPS.forEach((g) => {
      const n = g.key === 'all'
        ? all.length
        : all.filter(j => stateGroup(j.state) === g.key).length;
      if (g.key !== 'all' && !n) return;
      const on = g.key === 'all'
        ? filter.states.size === 0
        : filter.states.has(g.key);
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `filter-btn px-space-md py-2 rounded-full font-label-lg text-label-lg transition-all whitespace-nowrap ${on ? CHIP_ACTIVE : CHIP_OFF}`;
      chip.innerHTML = `${esc(t(g.i18n))} (${n})`;
      chip.dataset.state = g.key;
      chip.addEventListener('click', () => {
        if (g.key === 'all') {
          filter.states.clear();
        } else if (filter.states.has(g.key)) {
          filter.states.delete(g.key);
        } else {
          filter.states.add(g.key);
        }
        renderFilters();
        render();
      });
      queueFilters.appendChild(chip);
    });
  }

  /** 应用过滤。 */
  function visible() {
    const all = Array.from(jobs.values());
    return all.filter(j => {
      if (filter.states.size && !filter.states.has(stateGroup(j.state))) return false;
      if (filter.keyword) {
        const kw = filter.keyword.toLowerCase();
        const hay = `${j.title || ''} ${j.book_id || ''}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }

  /** 渲染队列 —— order-card 结构。 */
  function render() {
    const list = visible();

    if (!list.length) {
      queueList.innerHTML = `
        <div class="p-space-lg rounded-lg bg-surface-container-lowest/80 backdrop-blur-2xl border border-pink-100/80 shadow-[0_12px_32px_-8px_rgba(244,162,140,0.08)]">
          <div class="text-center py-space-xl">
            <div class="w-12 h-12 mx-auto rounded-full bg-pink-50 border border-pink-200/60 flex items-center justify-center mb-space-md">
              <span class="material-symbols-outlined text-outline text-[24px]">inbox</span>
            </div>
            <div class="font-headline-sm text-headline-sm text-on-surface">${esc(t('ingest.empty'))}</div>
            <div class="font-body-md text-body-md text-on-surface-variant mt-1">${esc(t('ingest.emptyHint'))}</div>
          </div>
        </div>`;
      if (paginationCountText) {
        paginationCountText.innerHTML = `Showing <strong>0</strong> of <strong>0</strong> tasks`;
      }
      return;
    }

    queueList.innerHTML = list.map(j => {
      const st = STATE_STYLE[j.state] || STATE_STYLE.pending;
      const pill = STATE_PILL[j.state] || STATE_PILL.pending;
      const dot = STATE_DOT[j.state] || STATE_DOT.pending;
      const text = t('state.' + (j.state || 'pending')) || j.state;
      const detail = j.detail || j.error || '';
      const isActive = ACTIVE_STATES.indexOf(j.state) >= 0;

      // 标题行：书名 + 第二个标签 pill + 状态胶囊（与 orders.html 的 title pills 一致）
      // orders.html 第二个 pill 是「+330 Sparks」这种标签，和状态胶囊不是同一条信息；
      // 这里用作者承担这个位置，状态只出现一次。
      const tagPill = j.author
        ? `<span class="px-space-xs py-0.5 rounded-full bg-pink-50 border border-pink-200/80 text-[#9d5b74] font-label-sm text-label-sm font-semibold">${esc(j.author)}</span>`
        : '';
      const titlePills = `
              <span class="font-headline-sm text-headline-sm text-on-surface font-semibold">${esc(j.title)}</span>
              ${tagPill}
              <span class="px-space-sm py-0.5 rounded-full ${pill} font-label-sm text-label-sm font-semibold flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full ${dot}"></span> ${esc(text)}</span>`;

      // 元信息行：#id • 时间 • 加密来源（与 orders.html 的 meta 行一致）
      const meta = [];
      if (j.book_id) meta.push(`<span class="font-mono text-[#9d5b74] font-medium">#${esc(j.book_id)}</span>`);
      if (j.created_at) {
        const d = new Date(j.created_at * 1000);
        const date = d.toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric', timeZone: 'UTC' });
        const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
        meta.push(`<span>${esc(date)} • ${esc(time)} UTC</span>`);
      }
      if (j.license || j.source) {
        meta.push(`<span class="flex items-center gap-0.5"><span class="material-symbols-outlined text-[14px]">lock</span> ${esc(j.license || j.source)}</span>`);
      }
      const metaHtml = meta.length
        ? meta.map((m, i) => (i ? '<span>•</span>' : '') + m).join('')
        : '';

      // 右侧：文字块 + 两个按钮（与 orders.html 的右侧结构一致）
      const amount = j.bytes
        ? `${(j.bytes / 1048576).toFixed(1)} MB`
        : (isActive ? `${j.progress || 0}%` : t('ingest.noFile'));
      // 第二行是「金额的补充说明」，不能跟状态胶囊重复。
      const sub = (detail && detail !== text)
        ? detail
        : (j.license || j.source || '');
      const right = `
          <div class="flex flex-col text-left xl:text-right">
            <span class="font-headline-sm text-headline-sm text-on-surface font-bold">${esc(amount)}</span>
            <span class="font-label-sm text-label-sm text-on-surface-variant">${esc(sub)}</span>
          </div>
          <div class="flex items-center gap-space-xs shrink-0 flex-wrap sm:flex-nowrap">
            <a class="px-space-md py-2 rounded-full bg-white/90 border border-pink-200/80 hover:bg-pink-50/50 text-on-surface font-label-md text-label-md transition-all flex items-center gap-1 shadow-sm" href="/read/${encodeURIComponent(j.book_id)}">
              <span class="material-symbols-outlined text-[16px] text-[#9d5b74]">download</span>
              <span class="hidden sm:inline">${esc(t('ingest.downloadNote'))}</span>
            </a>
            <a class="px-space-md py-2 rounded-full bg-[#000000] text-white hover:bg-[#1f2937] font-label-md text-label-md transition-all flex items-center gap-1 shadow-sm" href="/read/${encodeURIComponent(j.book_id)}">
              <span>${esc(t('ingest.detail'))}</span>
              <span class="material-symbols-outlined text-[14px]">north_east</span>
            </a>
          </div>`;

      return `
      <div class="order-card p-space-lg rounded-lg bg-surface-container-lowest/80 backdrop-blur-2xl border border-pink-100/80 shadow-[0_12px_32px_-8px_rgba(244,162,140,0.08)] hover:shadow-[0_18px_40px_-10px_rgba(244,162,140,0.16)] transition-all flex flex-col xl:flex-row xl:items-center justify-between gap-space-lg group"
           data-query="${esc(((j.title || '') + ' ' + (j.book_id || '')).toLowerCase())}">
        <div class="flex items-start sm:items-center gap-space-md flex-wrap sm:flex-nowrap">
          <div class="w-12 h-12 rounded-full ${st.circle} flex items-center justify-center shrink-0 ${st.text} group-hover:scale-105 transition-transform">
            <span class="material-symbols-outlined text-[24px]">${st.icon}</span>
          </div>
          <div class="flex flex-col">
            <div class="flex items-center gap-space-xs flex-wrap">
              ${titlePills}
            </div>
            <div class="flex items-center gap-space-sm mt-1 text-on-surface-variant font-label-md text-label-md flex-wrap">
              ${metaHtml}
            </div>
          </div>
        </div>
        <div class="flex items-center justify-between xl:justify-end gap-space-lg pt-space-sm xl:pt-0">
          ${right}
        </div>
      </div>`;
    }).join('');

    if (paginationCountText) {
      paginationCountText.innerHTML =
        `Showing <strong>${list.length}</strong> of <strong>${jobs.size}</strong> tasks`;
    }
  }

  /** 处理单个任务更新。 */
  function upsert(job) {
    if (!job || !job.book_id) return;
    jobs.set(job.book_id, job);
    renderFilters();
    render();
  }

  /** 处理全量快照。 */
  function replaceAll(list) {
    jobs.clear();
    (list || []).forEach(j => jobs.set(j.book_id, j));
    renderFilters();
    render();
  }

  /* ---------------------------------------------------------- 交互 */

  input.addEventListener('input', updateCount);
  updateCount();

  queueSearch.addEventListener('input', () => {
    filter.keyword = queueSearch.value.trim();
    render();
  });

  // Enter 提交，Shift+Enter 换行
  input.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      if (!submitBtn.disabled) submitBtn.click();
    }
  });

  submitBtn.addEventListener('click', async () => {
    const titles = parseTitles();
    if (!titles.length) return;
    if (titles.length > 100) {
      toast(t('ingest.maxBooks'), true);
      return;
    }
    submitBtn.disabled = true;
    try {
      await api('/api/ingest', {
        method: 'POST',
        body: { titles },
      });
      toast(t('ingest.submitted', { n: titles.length }));
      input.value = '';
      updateCount();
    } catch (e) {
      toast(e.message, true);
    } finally {
      submitBtn.disabled = false;
      updateCount();
    }
  });

  subscribeJobs(replaceAll, upsert);
})();
