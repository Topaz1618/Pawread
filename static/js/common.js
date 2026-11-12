/* Pawread 前端公共部分
 *
 * 原生 ES6+，无框架、无构建步骤。
 */

/* ---------------------------------------------------------------- 工具 */

/** 发 JSON 请求。
 *
 * @param {string} url 地址
 * @param {object} [opts] 选项，body 会自动 JSON 化
 * @returns {Promise<any>} 解析后的响应体
 */
async function api(url, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, init);
  let data = null;
  try { data = await res.json(); } catch (e) { /* 非 JSON 响应 */ }
  if (!res.ok) {
    const msg = (data && data.error) || `请求失败（${res.status}）`;
    throw new Error(msg);
  }
  return data;
}

/** HTML 转义。
 *
 * @param {string} s 原始字符串
 * @returns {string} 转义后的字符串
 */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/** 弹一条提示。
 *
 * @param {string} msg 文字
 * @param {boolean} [isErr] 是否错误样式
 */
function toast(msg, isErr) {
  const host = document.getElementById('toastHost');
  if (!host) return;
  const el = document.createElement('div');
  el.className = 'toast' + (isErr ? ' err' : '');
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

/* ---------------------------------------------------------------- 进度环 */

/** 状态 → 圆环样式。
 *
 * 环用 SVG 的 stroke-dasharray 做进度条，
 * 转圈用 CSS 动画（.ring.spin）。
 *
 * 状态文字不在这里 —— 它在 `i18n.js` 的文案表里，
 * 按 `state.<name>` 取。
 */
const RING = {
  pending:    { color: 'var(--outline-variant)', spin: false, cls: '' },
  searching:  { color: 'var(--primary)',         spin: true,  cls: '' },
  downloading:{ color: 'var(--primary)',         spin: true,  cls: '' },
  verifying:  { color: 'var(--violet)',          spin: true,  cls: '' },
  noting:     { color: 'var(--primary-soft)',    spin: true,  cls: '' },
  available:  { color: 'var(--ok)',              spin: false, cls: 'ok' },
  noted:      { color: 'var(--ok)',              spin: false, cls: 'ok' },
  unavailable:{ color: 'var(--err)',             spin: false, cls: 'err' },
  failed:     { color: 'var(--err)',             spin: false, cls: 'err' },
};

/** 画一个进度环。
 *
 * @param {string} state 状态
 * @param {number} progress 百分比 0-100
 * @param {number} [size] 直径，默认 40
 * @returns {string} SVG 字符串
 */
function ringSvg(state, progress, size = 40) {
  const cfg = RING[state] || RING.pending;
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, progress || 0));
  const dash = (pct / 100) * c;
  const spinCls = cfg.spin ? ' spin' : '';
  const icon = cfg.spin
    ? ''
    : `<text x="50%" y="50%" text-anchor="middle" dy="0.35em"
             style="font-size:${size * 0.42}px;fill:${cfg.color}">${
             state === 'noted' || state === 'available' ? '✓' : '✕'}</text>`;
  return `<svg class="ring${cfg.cls}${spinCls}" width="${size}" height="${size}"
     viewBox="0 0 ${size} ${size}" style="transform-origin:50% 50%">
    <circle class="track" cx="${size / 2}" cy="${size / 2}" r="${r}"
            stroke-width="3"/>
    <circle class="bar" cx="${size / 2}" cy="${size / 2}" r="${r}"
            stroke-width="3" stroke="${cfg.color}"
            stroke-dasharray="${dash} ${c}"/>
    ${icon}
  </svg>`;
}

/* ---------------------------------------------------------------- 队列订阅 */

/**
 * 订阅任务进度。
 *
 * WebSocket 断了会自动重连，重连后先拉一次快照对齐。
 *
 * @param {function} onSnapshot 全量快照回调
 * @param {function} onJob 单个任务回调
 */
function subscribeJobs(onSnapshot, onJob) {
  let ws = null;
  let retry = 1000;

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/jobs`);

    ws.onopen = () => { retry = 1000; };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === 'snapshot') onSnapshot(msg.jobs || []);
      else if (msg.type === 'job') onJob(msg.job);
    };

    ws.onclose = () => {
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 15000);
    };

    ws.onerror = () => { try { ws.close(); } catch (e) { /* 已关闭 */ } };
  }

  connect();
}
