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
  el.className = `px-space-md py-space-sm rounded-lg font-label-md text-label-md shadow-lg ${
    isErr
      ? 'bg-red-50 text-red-700 border border-red-200/70'
      : 'bg-[#000000] text-white'}`;
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => el.remove(), 4000);
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
