// BP-3b 附录 B：G2 实时帧记录（【建议】工具，不是仓库代码）。
// 在工作台页面按 F12 → Console 粘贴执行；必须在点击“连接实时检测”之前执行，刷新页面后要重新粘贴。
// 只记录消息大小、类型、序号、错误码、置信度、朝向向量 R·(0,0,1) 和框中心 x；不记录图像、关键点或完整 R。
(() => {
  if (window.__g2) { console.log("G2 记录已安装"); return; }
  const T0 = performance.now();
  const now = () => Math.round(performance.now() - T0);
  const log = { started: new Date().toISOString(), ua: navigator.userAgent, events: [] };
  window.__g2 = log;
  let conns = 0;
  const Native = window.WebSocket;
  class LoggedSocket extends Native {
    constructor(url, protocols) {
      super(url, protocols);
      const conn = ++conns;
      this.__conn = conn;
      log.events.push({ k: "new", conn, t: now(), url: String(url) });
      this.addEventListener("open", () => log.events.push({ k: "open", conn, t: now() }));
      this.addEventListener("message", (ev) => {
        const e = { k: "recv", conn, t: now() };
        if (typeof ev.data === "string") {
          e.bytes = new TextEncoder().encode(ev.data).byteLength;
          try {
            const m = JSON.parse(ev.data);
            e.type = m.type; e.seq = m.seq; e.code = m.code;
            e.keys = Object.keys(m).sort().join(",");
            if (m.type === "face_state") {
              const R = m.pose.R;
              e.conf = m.conf;
              e.fwd = [R[2], R[5], R[8]].map((v) => Math.round(v * 1000) / 1000);
              e.cx = Math.round(m.bbox[0] + m.bbox[2] / 2);
            }
          } catch { e.type = "invalid-json"; }
        } else e.type = "binary";
        log.events.push(e);
      });
      this.addEventListener("close", (ev) => log.events.push({ k: "close", conn, t: now(), code: ev.code }));
      this.addEventListener("error", () => log.events.push({ k: "error", conn, t: now() }));
    }
    send(data) {
      log.events.push({ k: "send", conn: this.__conn, t: now(), bytes: data.size ?? data.byteLength ?? data.length });
      return super.send(data);
    }
  }
  window.WebSocket = LoggedSocket;
  window.__g2summary = () => {
    const out = [];
    for (let c = 1; c <= conns; c++) {
      const ev = log.events.filter((e) => e.conn === c);
      const sends = ev.filter((e) => e.k === "send");
      const terms = ev.filter((e) => e.k === "recv" && (e.type === "face_state" || e.type === "error"));
      let outstanding = 0, maxOutstanding = 0;
      for (const e of ev) {
        if (e.k === "send") maxOutstanding = Math.max(maxOutstanding, ++outstanding);
        if (e.k === "recv" && (e.type === "face_state" || e.type === "error")) outstanding--;
      }
      let maxPerSecond = 0;
      for (let i = 0, j = 0; i < sends.length; i++) {
        while (sends[i].t - sends[j].t >= 1000) j++;
        maxPerSecond = Math.max(maxPerSecond, i - j + 1);
      }
      const faces = terms.filter((e) => e.type === "face_state");
      const seqs = terms.map((e) => e.seq);
      const codes = {};
      terms.filter((e) => e.type === "error").forEach((e) => { codes[e.code] = (codes[e.code] || 0) + 1; });
      const span = sends.length > 1 ? (sends[sends.length - 1].t - sends[0].t) / 1000 : 0;
      out.push({
        conn: c,
        url: (ev.find((e) => e.k === "new") || {}).url,
        duration_s: ev.length ? (ev[ev.length - 1].t - ev[0].t) / 1000 : 0,
        sends: sends.length,
        max_send_bytes: Math.max(0, ...sends.map((e) => e.bytes || 0)),
        terminal_replies: terms.length,
        face_state: faces.length,
        error_codes: codes,
        status_msgs: ev.filter((e) => e.k === "recv" && e.type === "status").length,
        other_msgs: ev.filter((e) => e.k === "recv" && !["face_state", "error", "status"].includes(e.type)).length,
        seq_continuous_from_1: seqs.every((s, i) => s === i + 1),
        max_reply_bytes: Math.max(0, ...ev.filter((e) => e.k === "recv").map((e) => e.bytes || 0)),
        face_keys: [...new Set(faces.map((e) => e.keys))],
        max_outstanding: maxOutstanding,
        mean_send_rate: span ? Math.round((sends.length - 1) / span * 100) / 100 : null,
        max_sends_in_1s: maxPerSecond,
        fwd_x_range: faces.length ? [Math.min(...faces.map((e) => e.fwd[0])), Math.max(...faces.map((e) => e.fwd[0]))] : null,
        fwd_y_range: faces.length ? [Math.min(...faces.map((e) => e.fwd[1])), Math.max(...faces.map((e) => e.fwd[1]))] : null,
        close_codes: ev.filter((e) => e.k === "close").map((e) => e.code),
      });
    }
    return { started: log.started, ua: log.ua, connections: out };
  };
  console.log("G2 记录已安装。结束后执行：copy(JSON.stringify(__g2summary(), null, 2)) 和 copy(JSON.stringify(__g2))");
})();
