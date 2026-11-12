/* 操作页：提交书单 + 实时队列 */

(function () {
  'use strict';

  const T = window.PawreadI18n;
  const t = T.t;

  const input = document.getElementById('titleInput');
  const submitBtn = document.getElementById('submitBtn');
  const langSelect = document.getElementById('langSelect');
  const countHint = document.getElementById('countHint');
  const queueList = document.getElementById('queueList');
  const queueSummary = document.getElementById('queueSummary');
  const clearDoneBtn = document.getElementById('clearDoneBtn');

  /** 当前任务表：id → job。 */
  const jobs = new Map();

  /** 解析输入框里的书名。 */
  function parseTitles() {
    return input.value
      .split('\n')
      .map(s => s.trim())
      .filter(s => s.length > 0);
  }

  function updateCount() {
    const n = parseTitles().length;
    countHint.textContent = t('ingest.count', { n });
    submitBtn.disabled = n === 0;
  }

  /** 渲染队列。 */
  function render() {
    const list = Array.from(jobs.values());
    if (!list.length) {
      queueList.innerHTML = `
        <div class="card card-pad">
          <div class="empty" style="padding:40px 20px">
            <div class="empty-mark">
              <span class="material-symbols-outlined" style="font-size:28px">inbox</span>
            </div>
            <div class="t-body">${esc(t('ingest.empty'))}</div>
            <div class="t-label-sm t-faint" style="margin-top:6px">${esc(t('ingest.emptyHint'))}</div>
          </div>
        </div>`;
      queueSummary.textContent = '0';
      return;
    }

    const done = list.filter(j => j.state === 'noted').length;
    const failed = list.filter(j => j.state === 'failed' || j.state === 'unavailable').length;
    const running = list.length - done - failed;
    queueSummary.textContent = t('ingest.summary', {
      total: list.length, running, done, failed,
    });

    queueList.innerHTML = list.map(j => {
      const text = t('state.' + (j.state || 'pending')) || j.state;
      const detail = j.detail || j.error || '';
      const sub = detail ? `${text} · ${esc(detail)}`
                : (j.source ? `${text} · ${esc(j.source)}` : text);
      const iconCls = (j.state === 'noted') ? 'icon-lav'
                    : (j.state === 'failed' || j.state === 'unavailable') ? 'icon-mute'
                    : 'icon-rose';
      const iconName = (j.state === 'noted') ? 'task_alt'
                     : (j.state === 'failed') ? 'error'
                     : (j.state === 'unavailable') ? 'block' : 'menu_book';
      return `
      <div class="list-card">
        <div class="list-icon ${iconCls}">
          <span class="material-symbols-outlined" style="font-size:24px">${iconName}</span>
        </div>
        <div style="min-width:0;flex:1">
          <div class="list-title">${esc(j.title)}</div>
          <div class="list-meta">
            <span>${esc(sub)}</span>
            ${j.source_url ? '<span class="sep">•</span><span>' + esc(j.source) + '</span>' : ''}
          </div>
        </div>
        <div class="list-actions">
          ${ringSvg(j.state, j.progress, 40)}
          ${j.state === 'noted'
            ? `<a class="btn btn-ghost btn-sm" href="/read/${encodeURIComponent(j.book_id)}">${esc(t('ingest.read'))}</a>`
            : ''}
        </div>
      </div>`;
    }).join('');
  }

  /** 处理单个任务更新。 */
  function upsert(job) {
    if (!job || !job.book_id) return;
    jobs.set(job.book_id, job);
    render();
  }

  /** 处理全量快照。 */
  function replaceAll(list) {
    jobs.clear();
    (list || []).forEach(j => jobs.set(j.book_id, j));
    render();
  }

  /* ---------------------------------------------------------- 交互 */

  input.addEventListener('input', updateCount);
  updateCount();

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
        body: { titles, lang: langSelect.value },
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

  clearDoneBtn.addEventListener('click', () => {
    let n = 0;
    for (const [id, j] of jobs) {
      if (j.state === 'noted' || j.state === 'failed' || j.state === 'unavailable') {
        jobs.delete(id);
        n++;
      }
    }
    render();
    if (n) toast(`${n} cleared`);
  });

  subscribeJobs(replaceAll, upsert);
})();