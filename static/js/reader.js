/* 阅读页：侧边栏书单 + Markdown 渲染 + 阅读位置
 *
 * 样式全部来自模板的 utility 类名，
 * 这里只负责生成 DOM 与数据绑定。
 */

(function () {
  'use strict';

  const T = window.PawreadI18n;
  const t = T.t;

  const BOOK_ID = window.PAWREAD_BOOK_ID || '';
  const mdRoot = document.getElementById('mdRoot');
  const readerMain = document.getElementById('readerMain') || window;
  const sideList = document.getElementById('sideList');
  const readProgress = document.getElementById('readProgress');

  /** 全部书（侧边栏用）。 */
  let books = [];

  /* ---------------------------------------------------------- Markdown */

  if (window.marked) {
    window.marked.setOptions({
      gfm: true,
      breaks: false,
      headerIds: false,
      mangle: false,
    });
  }

  /** 渲染 Markdown。
   *
   * @param {string} md Markdown 原文
   * @returns {string} HTML
   */
  function renderMd(md) {
    if (window.marked) return window.marked.parse(md);
    // 没有 marked 时退回最简渲染，至少标题能看
    return '<pre>' + esc(md) + '</pre>';
  }

  /** 目录里的锚点跳转 —— 标题统一生成 id。 */
  function slugifyAnchor(text) {
    return String(text).trim().toLowerCase()
      .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  /** 给渲染后的标题补 id。 */
  function addHeadingIds(root) {
    const seen = {};
    root.querySelectorAll('h1, h2, h3, h4').forEach(h => {
      let id = slugifyAnchor(h.textContent) || 'section';
      if (seen[id]) { seen[id] += 1; id = `${id}-${seen[id]}`; }
      else { seen[id] = 1; }
      h.id = id;
    });
  }

  /* ---------------------------------------------------------- 侧边栏 */

  /** 渲染侧边栏书单 —— 结构照搬 chat2.html 的 nav 列表项。 */
  function renderSide() {
    const noted = books.filter(b => b.has_note);
    if (!noted.length) {
      sideList.innerHTML = `<div class="font-body-md text-body-md text-on-surface-variant px-space-sm py-space-sm">${esc(t('reader.noNote'))}</div>`;
      return;
    }
    sideList.innerHTML = noted.map(b => {
      // 原书名做主标题，当前语言的译名做副标题
      const title = b.original_title || b.title?.text || b.display_title || '';
      const zh = b.display_title && b.display_title !== title
        ? `<span class="block font-label-sm text-label-sm text-on-surface-variant opacity-70 mt-0.5 truncate">${esc(b.display_title)}</span>`
        : '';
      const active = b.id === BOOK_ID
        ? 'bg-surface-container text-on-surface font-bold'
        : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface';
      return `<a class="flex items-center gap-space-sm px-space-sm py-space-sm rounded-DEFAULT transition-all ${active} font-body-md text-body-md"
                 href="/read/${encodeURIComponent(b.id)}">
        <span class="material-symbols-outlined text-[20px] shrink-0">menu_book</span>
        <span class="min-w-0 flex-1">
          <span class="block truncate">${esc(title)}</span>
          ${zh}
        </span>
      </a>`;
    }).join('');
  }

  /* ---------------------------------------------------------- 阅读位置 */

  /** 读进度。
   *
   * @returns {number} 0-1
   */
  function getProgress() {
    try {
      const raw = localStorage.getItem('pawread:progress:' + BOOK_ID);
      return raw ? parseFloat(raw) || 0 : 0;
    } catch (e) { return 0; }
  }

  /** 存进度。 */
  function saveProgress() {
    if (!BOOK_ID) return;
    const max = readerMain.scrollHeight - readerMain.clientHeight;
    const p = max > 0 ? readerMain.scrollTop / max : 0;
    try {
      localStorage.setItem('pawread:progress:' + BOOK_ID, String(p));
    } catch (e) { /* 隐私模式下写不了，忽略 */ }
    const pct = Math.round(p * 100);
    if (readProgress) readProgress.textContent = pct + '%';
    // 后端也存一份，换设备能用
    api(`/api/notes/${encodeURIComponent(BOOK_ID)}/progress`, {
      method: 'POST', body: { progress: p },
    }).catch(() => { /* 存不上不影响阅读 */ });
  }

  let saveTimer = null;
  window.addEventListener('scroll', () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveProgress, 800);
  });

  /** 恢复滚动位置。 */
  function restoreProgress() {
    const p = getProgress();
    if (p > 0.01) {
      window.scrollTo(0, (document.body.scrollHeight - window.innerHeight) * p);
      if (readProgress) readProgress.textContent = Math.round(p * 100) + '%';
    }
  }

  /* ---------------------------------------------------------- 快捷键 */

  document.addEventListener('keydown', ev => {
    if (ev.target.matches('input, textarea, select')) return;
    if (ev.key === 'Escape') { location.href = '/library'; }
    if (ev.key === 'j' || ev.key === 'ArrowDown') {
      window.scrollBy({ top: 120, behavior: 'smooth' });
    }
    if (ev.key === 'k' || ev.key === 'ArrowUp') {
      window.scrollBy({ top: -120, behavior: 'smooth' });
    }
  });

  /* ---------------------------------------------------------- 初始化 */

  api(`/api/books?lang=${encodeURIComponent(T.getLang())}`)
    .then(data => { books = data.books || []; renderSide(); })
    .catch(() => { /* 侧边栏失败不阻塞正文 */ });

  api(`/api/notes/${encodeURIComponent(BOOK_ID)}`)
    .then(data => {
      mdRoot.innerHTML = renderMd(data.markdown || '');
      addHeadingIds(mdRoot);
      // 图片加懒加载，表格加横向滚动
      mdRoot.querySelectorAll('img').forEach(img => { img.loading = 'lazy'; });
      mdRoot.querySelectorAll('table').forEach(tb => {
        const wrap = document.createElement('div');
        wrap.style.overflowX = 'auto';
        tb.parentNode.insertBefore(wrap, tb);
        wrap.appendChild(tb);
      });
      restoreProgress();
    })
    .catch(e => {
      mdRoot.innerHTML = `
        <div class="text-center py-space-xl">
          <div class="w-12 h-12 mx-auto rounded-full bg-pink-50 border border-pink-200/60 flex items-center justify-center mb-space-md">
            <span class="material-symbols-outlined text-[#9d5b74] text-[24px]">error</span>
          </div>
          <div class="font-body-md text-body-md text-on-surface-variant">${esc(e.message)}</div>
          <a class="inline-block mt-space-md px-space-md py-2 rounded-full bg-[#000000] text-white font-label-md text-label-md"
             href="/library">${esc(t('reader.back'))}</a>
        </div>`;
    });
})();