/* CareerPilot Ops client helpers (HTMX + Alpine + Chart.js pages). */
window.CPOps = {
  csrf() {
    const el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.content : '';
  },
  async control(action) {
    const body = new FormData();
    body.append('csrf_token', this.csrf());
    const res = await fetch('/api/control/' + action, {
      method: 'POST',
      body,
      headers: { 'X-CSRF-Token': this.csrf() },
    });
    return res.json();
  },
  fmtUptime(sec) {
    sec = Math.floor(sec || 0);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  },
  connectLive(onTick) {
    let ws;
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/ws/live`);
      ws.onmessage = (ev) => {
        try { onTick(JSON.parse(ev.data)); } catch (_) {}
      };
      ws.onclose = () => setTimeout(connect, 3000);
    };
    connect();
    return () => { try { ws && ws.close(); } catch (_) {} };
  },
};
