/* Dashboard page */

const XRAY_GROUP_TEST_CONCURRENCY = 8;

// ISO 3166-1 alpha-2 country code ("DE") -> flag emoji ("🇩🇪")
// using regional indicator symbols. Returns "" for invalid input.
function countryCodeToFlag(cc) {
  if (!cc || cc.length !== 2) return '';
  const A = 0x1F1E6;
  const a = 'A'.charCodeAt(0);
  const up = cc.toUpperCase();
  if (!/^[A-Z]{2}$/.test(up)) return '';
  return String.fromCodePoint(A + up.charCodeAt(0) - a,
                              A + up.charCodeAt(1) - a);
}

const BandwidthChart = {
  MAX_POINTS: 60,       // 5 min / 5 sec = 60 data points
  INTERVAL: 5000,       // 5 seconds
  history: [],          // [{ts, vpn_rx, vpn_tx, lan_rx, lan_tx}] rates in bytes/sec
  prev: null,           // previous raw bytes for delta calc
  prevTs: 0,
  activeInterfaceKey: null,
  activeInterfaceName: null,
  timer: null,
  canvas: null,
  ctx: null,

  init() {
    this.canvas = document.getElementById('bw-canvas');
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.tick();
    this.timer = setInterval(() => this.tick(), this.INTERVAL);
  },

  destroy() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    window.removeEventListener('resize', () => this.resize());
  },

  resize() {
    this.canvas = document.getElementById('bw-canvas');
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = 200 * dpr;
    this.canvas.style.width = rect.width + 'px';
    this.canvas.style.height = '200px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  },

  async tick() {
    const data = await API.get('/system/status');
    if (!data) return;
    const now = Date.now();
    const externalIface = this.getExternalInterface(data);
    const external = data.external_tunnel || {};
    const ifaceName = externalIface.name || external.interface || 'VPN';
    const ifaceKey = `${external.type || 'unknown'}:${ifaceName}`;

    if (this.activeInterfaceKey && this.activeInterfaceKey !== ifaceKey) {
      this.history = [];
      this.prev = null;
      this.prevTs = 0;
    }
    this.activeInterfaceKey = ifaceKey;
    this.activeInterfaceName = ifaceName;

    const raw = {
      vpn_rx: externalIface.rx_bytes || 0,
      vpn_tx: externalIface.tx_bytes || 0,
      lan_rx: data.lan.rx_bytes,
      lan_tx: data.lan.tx_bytes,
    };

    if (this.prev && this.prevTs) {
      const dt = (now - this.prevTs) / 1000;
      if (dt > 0) {
        this.history.push({
          ts: now,
          vpn_rx: Math.max(0, (raw.vpn_rx - this.prev.vpn_rx) / dt),
          vpn_tx: Math.max(0, (raw.vpn_tx - this.prev.vpn_tx) / dt),
          lan_rx: Math.max(0, (raw.lan_rx - this.prev.lan_rx) / dt),
          lan_tx: Math.max(0, (raw.lan_tx - this.prev.lan_tx) / dt),
        });
        if (this.history.length > this.MAX_POINTS) this.history.shift();
      }
    }
    this.prev = raw;
    this.prevTs = now;
    this.draw();
    this.updateLegend();
  },

  getExternalInterface(data) {
    const external = data.external_tunnel || {};
    const vpn = data.vpn || {};
    const xray = data.xray_tun || {};

    if (external.type === 'xray') return xray;
    if (external.type === 'amnezia') return vpn;
    if (external.interface && external.interface === xray.name) return xray;
    if (external.interface && external.interface === vpn.name) return vpn;
    return vpn;
  },

  updateLegend() {
    const last = this.history.length ? this.history[this.history.length - 1] : null;
    const vpnLabel = this.activeInterfaceName ? `VPN (${this.activeInterfaceName})` : 'VPN';
    const labelDown = document.getElementById('bw-vpn-label');
    const labelUp = document.getElementById('bw-vpn-label-up');
    if (labelDown) labelDown.textContent = vpnLabel;
    if (labelUp) labelUp.textContent = vpnLabel;
    const el = (id, val) => {
      const e = document.getElementById(id);
      if (e) e.textContent = last ? formatBytes(val) + '/s' : '—';
    };
    if (last) {
      el('bw-vpn-dl', last.vpn_rx);
      el('bw-vpn-ul', last.vpn_tx);
      el('bw-lan-dl', last.lan_rx);
      el('bw-lan-ul', last.lan_tx);
    }
  },

  draw() {
    this.canvas = document.getElementById('bw-canvas');
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    const ctx = this.ctx;
    const W = this.canvas.style.width ? parseInt(this.canvas.style.width) : 600;
    const H = 200;
    const PAD = {top: 10, right: 12, bottom: 24, left: 55};
    const gW = W - PAD.left - PAD.right;
    const gH = H - PAD.top - PAD.bottom;

    ctx.clearRect(0, 0, W, H);

    // Find max value for scale
    let maxVal = 1024; // minimum 1 KB/s
    for (const p of this.history) {
      maxVal = Math.max(maxVal, p.vpn_rx, p.vpn_tx, p.lan_rx, p.lan_tx);
    }
    maxVal *= 1.15; // headroom

    // Grid lines
    ctx.strokeStyle = '#2a2d3e';
    ctx.lineWidth = 1;
    ctx.font = '11px system-ui, sans-serif';
    ctx.fillStyle = '#8b8fa3';
    ctx.textAlign = 'right';
    const gridLines = 4;
    for (let i = 0; i <= gridLines; i++) {
      const y = PAD.top + (gH * i / gridLines);
      ctx.beginPath();
      ctx.moveTo(PAD.left, y);
      ctx.lineTo(W - PAD.right, y);
      ctx.stroke();
      const val = maxVal * (1 - i / gridLines);
      ctx.fillText(formatBytes(val) + '/s', PAD.left - 6, y + 4);
    }

    // Time labels
    ctx.textAlign = 'center';
    ctx.fillStyle = '#8b8fa3';
    const timeLabels = ['-5m', '-4m', '-3m', '-2m', '-1m', 'now'];
    for (let i = 0; i < timeLabels.length; i++) {
      const x = PAD.left + (gW * i / (timeLabels.length - 1));
      ctx.fillText(timeLabels[i], x, H - 4);
    }

    if (this.history.length < 2) {
      ctx.fillStyle = '#8b8fa3';
      ctx.textAlign = 'center';
      ctx.font = '13px system-ui, sans-serif';
      ctx.fillText('Collecting data...', W / 2, H / 2);
      return;
    }

    // Draw lines
    const drawLine = (key, color) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      const len = this.history.length;
      for (let i = 0; i < len; i++) {
        const x = PAD.left + gW * (1 - (len - 1 - i) / (this.MAX_POINTS - 1));
        const y = PAD.top + gH * (1 - this.history[i][key] / maxVal);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };

    drawLine('vpn_rx', '#34d399');  // VPN Download — green
    drawLine('vpn_tx', '#6c8cff');  // VPN Upload — accent blue
    drawLine('lan_rx', '#f87171');  // LAN Download — red
    drawLine('lan_tx', '#a78bfa');  // LAN Upload — violet
  },

  html() {
    return `
      <div class="card bandwidth-card">
        <div class="card-title">Bandwidth</div>
        <div class="bw-legend">
          <span class="bw-legend-item"><span class="bw-dot" style="background:#34d399"></span><span id="bw-vpn-label">VPN</span> ↓ <b id="bw-vpn-dl">—</b></span>
          <span class="bw-legend-item"><span class="bw-dot" style="background:#6c8cff"></span><span id="bw-vpn-label-up">VPN</span> ↑ <b id="bw-vpn-ul">—</b></span>
          <span class="bw-legend-item"><span class="bw-dot" style="background:#f87171"></span>LAN ↓ <b id="bw-lan-dl">—</b></span>
          <span class="bw-legend-item"><span class="bw-dot" style="background:#a78bfa"></span>LAN ↑ <b id="bw-lan-ul">—</b></span>
        </div>
        <div class="bw-canvas-wrap"><canvas id="bw-canvas"></canvas></div>
      </div>
    `;
  }
};

const DashboardPage = {
  timer: null,
  xrayExpandedGroups: { standalone: true },
  amneziaPingResults: {},
  amneziaGroupPingResults: {},
  amneziaHardTestResults: {},
  amneziaGroupHardTestResults: {},
  xrayPingResults: {},
  xrayGroupPingResults: {},
  xrayHardTestResults: {},
  xrayGroupHardTestResults: {},

  isReadOnly() {
    return window.VPNGW_DASH_VIEW === true;
  },

  _escape(s) {
    const d = document.createElement('div');
    d.textContent = String(s || '');
    return d.innerHTML;
  },

  async render() {
    const readOnly = this.isReadOnly();
    const [data, modeData, configsData, xrayClient, xrayClientConfigs, ovpn, ovpnConfigs, xray] = await Promise.all([
      API.get('/system/status'),
      API.get('/routing/mode'),
      API.get('/vpn/configs'),
      API.get('/xray-client/status'),
      API.get('/xray-client/configs'),
      API.get('/openvpn/status'),
      API.get('/openvpn/configs'),
      API.get('/xray/status'),
    ]);
    if (!data) return '<div class="loading">Failed to load</div>';

    const vpn = data.vpn;
    const lan = data.lan;
    const res = data.resources;
    const conn = data.connectivity || {};
    const exit = data.exit_ip || {};
    const memPct = res.memory_percent;
    const mode = modeData ? modeData.mode : 'split';
    const modeLabels = { 'split': 'Split Tunneling', 'all-vpn': 'All VPN', 'all-direct': 'All Direct' };
    const modeColors = { 'split': 'var(--accent)', 'all-vpn': 'var(--green)', 'all-direct': 'var(--orange)' };
    const external = data.external_tunnel || { type: 'amnezia', interface: vpn.name, up: vpn.up };
    const vpnServiceOn = !!data.services?.['vpngw-vpn'];
    const vpnSelected = external.type === 'amnezia';
    const vpnStateLabel = vpnSelected && vpnServiceOn ? (vpn.up ? 'Connected' : 'Starting…') : (vpnServiceOn ? 'Standby' : 'Disabled');
    const vpnDotClass = vpnSelected && vpnServiceOn && vpn.up ? 'up' : (vpnSelected && vpnServiceOn ? 'pending' : 'down');
    const vpnToggleBtn = readOnly ? '' : `<button class="vpn-toggle ${vpnServiceOn ? 'on' : 'off'}"
                                  data-vpn-action="${vpnServiceOn ? 'stop' : 'start'}">
                            <span class="ovpn-toggle-track"><span class="ovpn-toggle-dot"></span></span>
                            <span class="ovpn-toggle-label">${vpnServiceOn ? 'On' : 'Off'}</span>
                          </button>`;

    // VPN config picker rendered on the right side of the VPN Tunnel card.
    const configs = (configsData && configsData.configs) || [];
    const activeConfig = configs.find(c => c.active);
    const groupPingResult = this._formatAmneziaGroupPingResult('all');
    const groupHardTest = this._formatAmneziaGroupHardTestHtml('all');
    const configsHtml = configs.length === 0
      ? '<div class="vpn-configs-empty">no configs</div>'
      : configs.map(c => {
          const f = countryCodeToFlag(c.country_code) || '🌐';
          const cls = c.active ? 'vpn-config active has-actions' : 'vpn-config has-actions';
          const label = c.display_name || c.country_name || c.name;
          const title = c.endpoint ? `${label} · ${c.endpoint}` : label;
          const pingResult = this._formatAmneziaConfigPingResult(c.name);
          const hardTest = this._formatAmneziaHardTestHtml(c.name);
          const deleteBtn = c.active ? ''
            : `<button class="xray-mini-btn xray-danger-btn" data-amnezia-config-delete="${c.name}" title="Delete config">×</button>`;
          return `<div class="${cls}" data-config="${c.name}" title="${title}">`
               + `<span class="vpn-config-flag">${f}</span>`
               + `<span class="vpn-config-name">${label}</span>`
               + `<span class="xray-ping-result" data-amnezia-ping-result="${c.name}">${pingResult}</span>`
               + `<button class="xray-config-ping" data-amnezia-config-ping="${c.name}" title="Ping config">ping</button>`
               + `<button class="xray-config-ping xray-hard-test-btn" data-amnezia-config-hard-test="${c.name}" title="Hard test config">${hardTest}</button>`
               + deleteBtn
               + (c.active ? '<span class="vpn-active-dot">●</span>' : '')
               + `</div>`;
        }).join('');
    const configsPanelHtml = readOnly ? '' : `
          <div class="vpn-configs" id="vpnConfigs">
            <div class="vpn-configs-title xray-configs-head">
              <span>Configs</span>
              ${configs.length ? `<span class="xray-ping-result xray-group-ping-result" data-amnezia-group-ping-result="all">${groupPingResult}</span>`
                + `<button class="xray-mini-btn" data-amnezia-group-ping="all" title="Ping all Amnezia configs">ping</button>`
                + `<button class="xray-mini-btn xray-hard-test-btn" data-amnezia-group-hard-test="all" title="Hard test all Amnezia configs">${groupHardTest}</button>` : ''}
              <button class="xray-mini-btn" data-amnezia-config-add="1" title="Add Amnezia .conf">+</button>
            </div>
            ${configsHtml}
          </div>`;

    // VPN Tunnel card body: stack three lines —
    //   endpoint  : WG handshake destination (from active config)
    //   tunnel    : amn0 interface IP (CGNAT, assigned by WG peer)
    //   exit pool : what each external probe sees as our public IP
    //               (provider source-NATs differently per destination,
    //                so a single "exit IP" is misleading)
    const ifaceIp = vpn.ip_address || 'No IP';
    const endpointHtml = activeConfig && activeConfig.endpoint
      ? `<div class="vpn-line"><span class="vpn-label">endpoint</span>`
        + `<span class="vpn-value">${countryCodeToFlag(activeConfig.country_code) || '🌐'} ${activeConfig.endpoint}</span>`
        + `</div>`
      : '';
    const tunnelHtml = `<div class="vpn-line"><span class="vpn-label">tunnel</span>`
                     + `<span class="vpn-value">${ifaceIp}</span></div>`;
    const probes = (exit.probes || []).filter(p => p && p.ip);
    let poolHtml = '';
    if (probes.length > 0) {
      poolHtml = `<div class="vpn-line vpn-pool"><span class="vpn-label">exit pool</span>`
               + `<div class="vpn-pool-items">`
               + probes.map(p => {
                   const f = countryCodeToFlag(p.country_code) || '🌐';
                   return `<div class="vpn-pool-item" title="${p.service}">`
                        + `<span class="vpn-pool-flag">${f}</span>`
                        + `<span class="vpn-pool-ip">${p.ip}</span>`
                        + `<span class="vpn-pool-svc">${p.service}</span>`
                        + `</div>`;
                 }).join('')
               + `</div></div>`;
    } else if (exit.ip) {
      // Backward-compat: legacy single-IP shape, no probes array
      poolHtml = `<div class="vpn-line"><span class="vpn-label">exit</span>`
               + `<span class="vpn-value">${countryCodeToFlag(exit.country_code) || '🌐'} ${exit.ip}</span>`
               + `</div>`;
    }
    const vpnBodyHtml = endpointHtml + tunnelHtml + (vpnSelected ? poolHtml : '');

    return `
      <div class="page-header">
        <h1 class="page-title">Dashboard</h1>
        <span style="padding:6px 14px;border-radius:6px;font-size:13px;font-weight:600;background:${modeColors[mode] || 'var(--accent)'};color:#fff">
          ${modeLabels[mode] || mode}
        </span>
      </div>

      <div class="card-grid dashboard-top">
        <div class="card vpn-tunnel-card">
          <div class="vpn-tunnel-main">
            <div class="vpn-tunnel-head">
              <div class="card-title">VPN Tunnel (${vpn.name})</div>
              ${vpnToggleBtn}
            </div>
            <div class="status">
              <span class="status-dot ${vpnDotClass}"></span>
              <span class="card-value" style="font-size:20px">${vpnStateLabel}</span>
            </div>
            <div class="vpn-info">${vpnBodyHtml}</div>
            <div class="card-sub" style="margin-top:6px">TX: ${formatBytes(vpn.tx_bytes)} / RX: ${formatBytes(vpn.rx_bytes)}</div>
          </div>
          ${configsPanelHtml}
        </div>

        ${this._renderXrayClientTunnelCard(xrayClient, xrayClientConfigs, external, poolHtml)}

        <div class="card dashboard-network-card">
          <div class="card-title">Network</div>
          <div class="status" style="margin-bottom:6px">
            <span class="status-dot ${lan.up ? 'up' : 'down'}"></span>
            <span class="card-value" style="font-size:18px">LAN ${lan.up ? 'Up' : 'Down'}</span>
          </div>
          <div class="card-sub">${lan.name}: ${lan.ip_address || 'No IP'}</div>
          <div class="card-sub" style="margin-bottom:8px">TX: ${formatBytes(lan.tx_bytes)} / RX: ${formatBytes(lan.rx_bytes)}</div>
          <div style="display:flex;align-items:center;gap:8px;padding:3px 0">
            <span class="status-dot ${conn.gateway?.reachable ? 'up' : 'down'}"></span>
            <span style="font-size:13px">Gateway ${conn.gateway?.ip || '?'}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;padding:3px 0">
            <span class="status-dot ${conn.internet?.reachable ? 'up' : 'down'}"></span>
            <span style="font-size:13px">Internet (${conn.internet?.target || '?'})</span>
          </div>
        </div>

        ${this._renderOpenvpnCard(ovpn, ovpnConfigs)}
        ${this._renderXrayCard(xray)}
      </div>

      ${BandwidthChart.html()}

      <div class="card-grid">
        <div class="card">
          <div class="card-title">Domains</div>
          <div class="card-value">${data.domains_count}</div>
          <div class="card-sub">routed through VPN</div>
        </div>

        <div class="card">
          <div class="card-title">IPSet Entries</div>
          <div class="card-value">${data.ipset_entries}</div>
          <div class="card-sub">IPs in vpn_domains</div>
        </div>

        <div class="card">
          <div class="card-title">Services</div>
          ${Object.entries(data.services).map(([name, active]) => `
            <div style="display:flex;align-items:center;gap:8px;padding:4px 0">
              <span class="status-dot ${active ? 'up' : 'down'}"></span>
              <span style="font-size:13px">${name}</span>
            </div>
          `).join('')}
        </div>

        <div class="card">
          <div class="card-title">System Resources</div>
          <div style="font-size:13px;margin-bottom:8px">${res.uptime}</div>
          <div class="card-sub">Memory: ${res.memory_used_mb} / ${res.memory_total_mb} MB (${memPct}%)</div>
          <div class="progress"><div class="progress-bar" style="width:${memPct}%;background:${memPct > 80 ? 'var(--red)' : 'var(--accent)'}"></div></div>
          <div class="card-sub" style="margin-top:8px">Load: ${res.load_average.join(', ')} &middot; CPU: ${res.cpu_count} core(s)</div>
        </div>
      </div>
    `;
  },

  _renderXrayClientTunnelCard(xrayClient, configsData, external, poolHtml) {
    const readOnly = this.isReadOnly();
    const configs = (configsData && configsData.configs) || [];

    if (!xrayClient) {
      return `<div class="card xray-client-card">
        <div class="card-title">VPN Tunnel (xray0)</div>
        <div class="card-sub">unavailable</div>
      </div>`;
    }

    const svc = xrayClient.service || {};
    const iface = xrayClient.interface || {};
    const selected = external && external.type === 'xray';
    const enabled = !!svc.active;
    const stateLabel = selected && enabled
      ? (iface.up ? 'Connected' : 'Starting…')
      : (enabled ? 'Standby' : 'Disabled');
    const dotClass = selected && enabled && iface.up ? 'up' : (selected && enabled ? 'pending' : 'down');
    const active = xrayClient.active || '';
    const endpoint = xrayClient.endpoint || '';
    const protocol = (xrayClient.protocol || '').toUpperCase();

    const configsHtml = this._renderXrayConfigGroups(configsData, readOnly);

    const configsPanelHtml = readOnly ? '' : `
        <div class="xray-client-configs" id="xrayClientConfigs">
          <div class="vpn-configs-title xray-configs-head">
            <span>Configs</span>
            <button class="xray-mini-btn" data-xray-config-add="1" title="Add standalone XRay .key">+key</button>
            <button class="xray-mini-btn" data-xray-subscription-add="1" title="Add subscription">+sub</button>
          </div>
          ${configsHtml}
        </div>`;

    const toggleBtn = readOnly ? '' : (active
      ? `<button class="xray-client-toggle ${enabled ? 'on' : 'off'}"
                 data-xray-client-action="${enabled ? 'disable' : 'enable'}">
           <span class="ovpn-toggle-track"><span class="ovpn-toggle-dot"></span></span>
           <span class="ovpn-toggle-label">${enabled ? 'On' : 'Off'}</span>
         </button>`
      : `<div class="card-sub" style="color:var(--orange)">no config selected</div>`);

    const tunnelHtml = `<div class="vpn-line"><span class="vpn-label">tunnel</span>`
                     + `<span class="vpn-value">${iface.ip_address || 'No IP'}</span></div>`;
    const endpointHtml = endpoint
      ? `<div class="vpn-line"><span class="vpn-label">endpoint</span>`
        + `<span class="vpn-value">${protocol ? protocol + ' ' : ''}${endpoint}</span></div>`
      : '';

    return `
      <div class="card xray-client-card">
        <div class="ovpn-head">
          <div class="card-title">VPN Tunnel (${iface.name || 'xray0'})</div>
          ${toggleBtn}
        </div>
        <div class="status" style="margin-bottom:6px">
          <span class="status-dot ${dotClass}"></span>
          <span class="card-value" style="font-size:18px">${stateLabel}</span>
        </div>
        ${active ? `<div class="card-sub">config: <b>${active}</b></div>` : ''}
        <div class="vpn-info">${endpointHtml}${tunnelHtml}${selected ? poolHtml : ''}</div>
        <div class="card-sub" style="margin-top:6px">TX: ${formatBytes(iface.tx_bytes || 0)} / RX: ${formatBytes(iface.rx_bytes || 0)}</div>
        ${configsPanelHtml}
      </div>
    `;
  },

  _renderXrayConfigGroups(configsData, readOnly) {
    const configs = (configsData && configsData.configs) || [];
    const groups = (configsData && configsData.groups && configsData.groups.length)
      ? configsData.groups
      : (configs.length ? [{ id: 'standalone', title: 'Standalone', kind: 'standalone', configs }] : []);

    if (!groups.length) return '<div class="vpn-configs-empty">no configs</div>';

    return groups.map(group => {
      const id = group.id || group.title || 'group';
      const expanded = this.xrayExpandedGroups[id] !== false;
      const items = group.configs || [];
      const refreshBtn = group.kind === 'subscription'
        ? `<button class="xray-mini-btn" data-xray-subscription-refresh="${id}" title="Refresh subscription">↻</button>`
        : '';
      const deleteBtn = group.kind === 'subscription'
        ? `<button class="xray-mini-btn xray-danger-btn" data-xray-subscription-delete="${id}" title="Delete subscription">×</button>`
        : '';
      const groupPingResult = this._formatXrayGroupPingResult(id);
      const groupHardTest = this._formatXrayGroupHardTestHtml(id);
      const testBtns = items.length
        ? `<span class="xray-ping-result xray-group-ping-result" data-xray-group-ping-result="${id}">${groupPingResult}</span>`
          + `<button class="xray-mini-btn" data-xray-client-group-ping="${id}" title="Ping group">ping</button>`
          + `<button class="xray-mini-btn xray-hard-test-btn" data-xray-client-group-hard-test="${id}" title="Hard test group">${groupHardTest}</button>`
        : '';
      const error = group.last_error
        ? `<div class="xray-group-error">${this._escape(group.last_error)}</div>`
        : '';
      const body = expanded
        ? `<div class="xray-client-group-body">
            ${items.length ? items.map(c => this._renderXrayConfigItem(c, readOnly)).join('') : '<div class="vpn-configs-empty">empty</div>'}
           </div>`
        : '';
      return `
        <div class="xray-client-group" data-xray-client-group="${id}">
          <div class="xray-client-group-head">
            <button class="xray-client-group-toggle" data-xray-client-group-toggle="${id}">
              <span class="xray-client-group-caret">${expanded ? '▾' : '▸'}</span>
              <span class="xray-client-group-title">${this._escape(group.title || id)}</span>
              <span class="xray-client-group-count">${items.length}</span>
            </button>
            ${refreshBtn}${deleteBtn}${testBtns}
          </div>
          ${error}
          ${body}
        </div>`;
    }).join('');
  },

  _renderXrayConfigItem(c, readOnly) {
    const cls = c.active ? 'xray-client-config active' : 'xray-client-config';
    const proto = (c.protocol || '').toUpperCase();
    const title = [c.name, proto, c.endpoint].filter(Boolean).join(' · ');
    const display = c.display_name || c.name.replace(/^xray-/, '');
    const pingResult = this._formatXrayConfigPingResult(c.name);
    const hardTest = this._formatXrayHardTestHtml(c.name);
    const ping = readOnly ? ''
      : `<span class="xray-ping-result" data-xray-ping-result="${c.name}">${pingResult}</span>`
        + `<button class="xray-config-ping" data-xray-client-config-ping="${c.name}" title="Ping config">ping</button>`
        + `<button class="xray-config-ping xray-hard-test-btn" data-xray-client-config-hard-test="${c.name}" title="Hard test config">${hardTest}</button>`;
    const deleteBtn = (!readOnly && !c.active && c.group === 'standalone' && !c.subscription_generated)
      ? `<button class="xray-mini-btn xray-danger-btn" data-xray-client-config-delete="${c.name}" title="Delete standalone config">×</button>`
      : '';
    return `<div class="${cls}" data-xray-client-config="${c.name}" title="${this._escape(title)}" tabindex="0">`
         + `<span class="ovpn-config-name">${this._escape(display)}</span>`
         + (proto ? `<span class="ovpn-config-endpoint">${this._escape(proto)}</span>` : '')
         + ping
         + deleteBtn
         + `</div>`;
  },

  _formatXrayConfigPingResult(name) {
    const result = this.xrayPingResults[name];
    if (!result || !result.ok) return 'n/a';
    const ms = Number(result.time_ms || 0);
    return ms > 0 ? `${ms} ms` : 'ok';
  },

  _formatXrayGroupPingResult(id) {
    const result = this.xrayGroupPingResults[id];
    if (!result) return 'n/a';
    if (result.completed && result.completed < result.total) {
      return `${result.okCount}/${result.completed}/${result.total}`;
    }
    if (!result.ok) return 'n/a';
    return `${result.okCount}/${result.total}`;
  },

  _formatXrayHardTestHtml(name) {
    const result = this.xrayHardTestResults[name];
    if (!result) return 'hard test';
    if (result.running) return '<span class="xray-hard-rate pending">...</span> hard test';
    const speed = Number(result.speed_bps || 0);
    const good = result.ok && speed > 0;
    const label = good ? (result.speed_label || this._formatRate(speed)) : '0';
    return `<span class="xray-hard-rate ${good ? 'ok' : 'fail'}">${this._escape(label)}</span> hard test`;
  },

  _formatXrayGroupHardTestHtml(id) {
    const result = this.xrayGroupHardTestResults[id];
    if (!result) return 'hard test';
    if (result.completed && result.completed < result.total) {
      return `<span class="xray-hard-rate pending">${result.okCount}/${result.completed}/${result.total}</span> hard test`;
    }
    if (result.okCount > 0) {
      return `<span class="xray-hard-rate ok">${result.okCount}/${result.total}</span> hard test`;
    }
    return '<span class="xray-hard-rate fail">0</span> hard test';
  },

  _formatRate(speedBps) {
    if (speedBps >= 1024 * 1024) return `${(speedBps / 1024 / 1024).toFixed(2)} MB/s`;
    if (speedBps >= 1024) return `${Math.round(speedBps / 1024)} KB/s`;
    return `${Math.round(speedBps)} B/s`;
  },

  _xrayGroupConfigNames(groupId) {
    return [...document.querySelectorAll(`[data-xray-client-group="${CSS.escape(groupId)}"] [data-xray-client-config]`)]
      .map(item => item.dataset.xrayClientConfig)
      .filter(Boolean);
  },

  _xrayConfigNames() {
    return [...document.querySelectorAll('#xrayClientConfigs [data-xray-client-config]')]
      .map(item => item.dataset.xrayClientConfig)
      .filter(Boolean);
  },

  async _runXrayGroupWorkers(names, worker, concurrency = XRAY_GROUP_TEST_CONCURRENCY) {
    const queue = [...names];
    const workerCount = Math.min(concurrency, queue.length);
    const workers = Array.from({ length: workerCount }, async () => {
      while (queue.length) {
        const name = queue.shift();
        if (name) await worker(name);
      }
    });
    await Promise.all(workers);
  },

  _setXrayPingResult(name, data) {
    this.xrayPingResults[name] = data && data.ok ? data : { ...(data || {}), name, ok: false };
    document.querySelectorAll(`[data-xray-ping-result="${CSS.escape(name)}"]`).forEach(el => {
      el.textContent = this._formatXrayConfigPingResult(name);
    });
  },

  _setXrayGroupPingResult(groupId, names, completed) {
    const okCount = names.filter(name => {
      const r = this.xrayPingResults[name];
      return r && r.ok;
    }).length;
    this.xrayGroupPingResults[groupId] = {
      ok: okCount > 0,
      okCount,
      completed,
      total: names.length,
    };
    document.querySelectorAll(`[data-xray-group-ping-result="${CSS.escape(groupId)}"]`).forEach(el => {
      el.textContent = this._formatXrayGroupPingResult(groupId);
    });
  },

  _setXrayHardTestResult(name, data) {
    this.xrayHardTestResults[name] = data && data.ok ? data : { ...(data || {}), name, ok: false, speed_bps: 0, speed_label: '0' };
    document.querySelectorAll(`[data-xray-client-config-hard-test="${CSS.escape(name)}"]`).forEach(el => {
      el.innerHTML = this._formatXrayHardTestHtml(name);
    });
  },

  _setXrayHardTestRunning(name, running) {
    this.xrayHardTestResults[name] = { ...(this.xrayHardTestResults[name] || {}), name, running };
    document.querySelectorAll(`[data-xray-client-config-hard-test="${CSS.escape(name)}"]`).forEach(el => {
      el.innerHTML = this._formatXrayHardTestHtml(name);
    });
  },

  _setXrayGroupHardTestResult(groupId, names, completed) {
    const okCount = names.filter(name => {
      const r = this.xrayHardTestResults[name];
      return r && r.ok && Number(r.speed_bps || 0) > 0;
    }).length;
    this.xrayGroupHardTestResults[groupId] = {
      ok: okCount > 0,
      okCount,
      completed,
      total: names.length,
    };
    document.querySelectorAll(`[data-xray-client-group-hard-test="${CSS.escape(groupId)}"]`).forEach(el => {
      el.innerHTML = this._formatXrayGroupHardTestHtml(groupId);
    });
  },

  _formatAmneziaConfigPingResult(name) {
    const result = this.amneziaPingResults[name];
    if (!result || !result.ok) return 'n/a';
    const ms = Number(result.time_ms || 0);
    return ms > 0 ? `${ms} ms` : 'ok';
  },

  _formatAmneziaGroupPingResult(id) {
    const result = this.amneziaGroupPingResults[id];
    if (!result) return 'n/a';
    if (result.completed && result.completed < result.total) {
      return `${result.okCount}/${result.completed}/${result.total}`;
    }
    if (!result.ok) return 'n/a';
    return `${result.okCount}/${result.total}`;
  },

  _formatAmneziaHardTestHtml(name) {
    const result = this.amneziaHardTestResults[name];
    if (!result) return 'hard test';
    if (result.running) return '<span class="xray-hard-rate pending">...</span> hard test';
    const speed = Number(result.speed_bps || 0);
    const good = result.ok && speed > 0;
    const label = good ? (result.speed_label || this._formatRate(speed)) : '0';
    return `<span class="xray-hard-rate ${good ? 'ok' : 'fail'}">${this._escape(label)}</span> hard test`;
  },

  _formatAmneziaGroupHardTestHtml(id) {
    const result = this.amneziaGroupHardTestResults[id];
    if (!result) return 'hard test';
    if (result.completed && result.completed < result.total) {
      return `<span class="xray-hard-rate pending">${result.okCount}/${result.completed}/${result.total}</span> hard test`;
    }
    if (result.okCount > 0) {
      return `<span class="xray-hard-rate ok">${result.okCount}/${result.total}</span> hard test`;
    }
    return '<span class="xray-hard-rate fail">0</span> hard test';
  },

  _amneziaConfigNames() {
    return [...document.querySelectorAll('#vpnConfigs [data-config]')]
      .map(item => item.dataset.config)
      .filter(Boolean);
  },

  _setAmneziaPingResult(name, data) {
    this.amneziaPingResults[name] = data && data.ok ? data : { ...(data || {}), name, ok: false };
    document.querySelectorAll(`[data-amnezia-ping-result="${CSS.escape(name)}"]`).forEach(el => {
      el.textContent = this._formatAmneziaConfigPingResult(name);
    });
  },

  _setAmneziaGroupPingResult(groupId, names, completed) {
    const okCount = names.filter(name => {
      const r = this.amneziaPingResults[name];
      return r && r.ok;
    }).length;
    this.amneziaGroupPingResults[groupId] = {
      ok: okCount > 0,
      okCount,
      completed,
      total: names.length,
    };
    document.querySelectorAll(`[data-amnezia-group-ping-result="${CSS.escape(groupId)}"]`).forEach(el => {
      el.textContent = this._formatAmneziaGroupPingResult(groupId);
    });
  },

  _setAmneziaHardTestResult(name, data) {
    this.amneziaHardTestResults[name] = data && data.ok ? data : { ...(data || {}), name, ok: false, speed_bps: 0, speed_label: '0' };
    document.querySelectorAll(`[data-amnezia-config-hard-test="${CSS.escape(name)}"]`).forEach(el => {
      el.innerHTML = this._formatAmneziaHardTestHtml(name);
    });
  },

  _setAmneziaHardTestRunning(name, running) {
    this.amneziaHardTestResults[name] = { ...(this.amneziaHardTestResults[name] || {}), name, running };
    document.querySelectorAll(`[data-amnezia-config-hard-test="${CSS.escape(name)}"]`).forEach(el => {
      el.innerHTML = this._formatAmneziaHardTestHtml(name);
    });
  },

  _setAmneziaGroupHardTestResult(groupId, names, completed) {
    const okCount = names.filter(name => {
      const r = this.amneziaHardTestResults[name];
      return r && r.ok && Number(r.speed_bps || 0) > 0;
    }).length;
    this.amneziaGroupHardTestResults[groupId] = {
      ok: okCount > 0,
      okCount,
      completed,
      total: names.length,
    };
    document.querySelectorAll(`[data-amnezia-group-hard-test="${CSS.escape(groupId)}"]`).forEach(el => {
      el.innerHTML = this._formatAmneziaGroupHardTestHtml(groupId);
    });
  },

  // OpenVPN dashboard tile — separate widget that takes the slot the
  // standalone "Internet" tile used to occupy. Shows current state, a
  // toggle, the active config, server endpoint, tunnel addresses, and
  // any subnets the server pushed at connect time (rendered as chips).
  _renderOpenvpnCard(ovpn, configsData) {
    const readOnly = this.isReadOnly();
    const configs = (configsData && configsData.configs) || [];
    if (configs.length === 0) return '';

    if (!ovpn) {
      return `<div class="card ovpn-card">
        <div class="card-title">OpenVPN</div>
        <div class="card-sub">unavailable</div>
      </div>`;
    }
    const svc = ovpn.service || {};
    const iface = ovpn.interface || {};
    const enabled = !!svc.active;
    const stateLabel = enabled
      ? (iface.up ? 'Connected' : 'Starting…')
      : 'Disabled';
    const dotClass = enabled && iface.up ? 'up' : (enabled ? 'pending' : 'down');
    const active = ovpn.active;
    const endpoint = ovpn.endpoint || '';
    const localIp = ovpn.local_ip || '';
    const remoteIp = ovpn.remote_ip || '';
    const routes = (ovpn.pushed_routes || []);
    const configsHtml = configs.map(c => {
      const cls = c.active ? 'ovpn-config active' : 'ovpn-config';
      const title = c.endpoint ? `${c.name} · ${c.endpoint}` : c.name;
      return `<button class="${cls}" data-ovpn-config="${c.name}" title="${title}">`
           + `<span class="ovpn-config-name">${c.name}</span>`
           + (c.endpoint ? `<span class="ovpn-config-endpoint">${c.endpoint}</span>` : '')
           + `</button>`;
    }).join('');
    const configsPanelHtml = readOnly ? '' : `
        <div class="ovpn-configs" id="ovpnConfigs">
          <div class="vpn-configs-title">Configs</div>
          ${configsHtml}
        </div>`;
    const routeChips = routes.length
      ? `<div class="ovpn-routes">${
          routes.map(r => `<span class="ovpn-route">${r}</span>`).join('')
        }</div>`
      : (enabled && iface.up
          ? `<div class="card-sub" style="opacity:0.7">no pushed routes</div>`
          : '');

    const toggleBtn = readOnly ? '' : (active
      ? `<button class="ovpn-toggle ${enabled ? 'on' : 'off'}"
                 data-action="${enabled ? 'disable' : 'enable'}">
           <span class="ovpn-toggle-track"><span class="ovpn-toggle-dot"></span></span>
           <span class="ovpn-toggle-label">${enabled ? 'On' : 'Off'}</span>
         </button>`
      : `<div class="card-sub" style="color:var(--orange)">no config selected</div>`);

    return `
      <div class="card ovpn-card">
        <div class="ovpn-head">
          <div class="card-title">OpenVPN</div>
          ${toggleBtn}
        </div>
        <div class="status" style="margin-bottom:6px">
          <span class="status-dot ${dotClass}"></span>
          <span class="card-value" style="font-size:18px">${stateLabel}</span>
        </div>
        ${active ? `<div class="card-sub">config: <b>${active}</b></div>` : ''}
        ${endpoint ? `<div class="card-sub">remote: ${endpoint}</div>` : ''}
        ${(localIp || remoteIp)
          ? `<div class="card-sub">tun: ${localIp || '?'} ↔ ${remoteIp || '?'}</div>`
          : ''}
        ${routeChips}
        ${configsPanelHtml}
      </div>
    `;
  },

  // XRay (VLESS+XHTTP) dashboard tile — cloud-VM-only inbound that
  // accepts client connections from public-internet apps and re-egresses
  // them through amn0. Hidden entirely on installations where xray was
  // never initialised (no server-params.json), so the home gateway UI
  // doesn't grow a useless card.
  _renderXrayCard(xray) {
    const readOnly = this.isReadOnly();
    if (!xray) return '';              // /xray/status unreachable
    if (!xray.configured) return '';   // a local installation / fresh install — hide

    const svc = xray.service || {};
    const enabled = !!svc.active;
    const stateLabel = enabled ? 'Listening' : 'Disabled';
    const dotClass = enabled ? 'up' : 'down';
    const host = xray.public_host || '';
    const clientCount = xray.client_count || 0;
    const stats = xray.stats || {};
    // Bytes aggregated by direction relative to the client:
    //   ↓ to clients   = what the proxy delivered to clients (xray's
    //                    outbound DOWNLINK — data fetched from the
    //                    internet on the clients' behalf)
    //   ↑ from clients = what the clients sent through us (xray's
    //                    outbound UPLINK — data we relayed up to the
    //                    internet for them)
    const downToClients = stats.outbound_downlink || 0;
    const upFromClients = stats.outbound_uplink   || 0;
    const trafficHtml = (typeof stats.inbound_uplink === 'number')
      ? `<div class="card-sub">↓ to clients: ${formatBytes(downToClients)} · ↑ from clients: ${formatBytes(upFromClients)}</div>`
      : (enabled
          ? `<div class="card-sub" style="opacity:0.7">no stats yet</div>`
          : '');

    const toggleBtn = readOnly ? '' : `<button class="ovpn-toggle ${enabled ? 'on' : 'off'}"
                                data-xray-action="${enabled ? 'disable' : 'enable'}">
                         <span class="ovpn-toggle-track"><span class="ovpn-toggle-dot"></span></span>
                         <span class="ovpn-toggle-label">${enabled ? 'On' : 'Off'}</span>
                       </button>`;
    const clientsAction = readOnly ? '' : `
          <button class="xray-clients-link" data-xray-clients="1">manage…</button>`;

    return `
      <div class="card ovpn-card xray-card">
        <div class="ovpn-head">
          <div class="card-title">XRay (VLESS)</div>
          ${toggleBtn}
        </div>
        <div class="status" style="margin-bottom:6px">
          <span class="status-dot ${dotClass}"></span>
          <span class="card-value" style="font-size:18px">${stateLabel}</span>
        </div>
        ${host ? `<div class="card-sub">host: <b>${host}</b></div>` : ''}
        <div class="card-sub">
          clients: <b>${clientCount}</b>
          ${clientsAction}
        </div>
        ${trafficHtml}
      </div>
    `;
  },

  // POST /xray/(enable|disable), then re-render. Mirrors _onOvpnToggle.
  async _onXrayToggle(ev) {
    const btn = ev.target.closest('[data-xray-action]');
    if (!btn || btn.classList.contains('busy')) return;
    const action = btn.dataset.xrayAction;
    if (action !== 'enable' && action !== 'disable') return;

    btn.classList.add('busy');
    try {
      const resp = await fetch(`/api/v1/xray/${action}`, { method: 'POST' });
      const body = await resp.json();
      if (body.status !== 'ok') {
        alert(`XRay ${action} failed: ${body.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`XRay ${action} failed: ${e}`);
    } finally {
      if (location.hash.replace('#', '') === '/') {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }
    }
  },

  async _onXrayClientToggle(ev) {
    const btn = ev.target.closest('[data-xray-client-action]');
    if (!btn || btn.classList.contains('busy')) return;
    const action = btn.dataset.xrayClientAction;
    if (action !== 'enable' && action !== 'disable') return;

    btn.classList.add('busy');
    try {
      const resp = await fetch(`/api/v1/xray-client/${action}`, { method: 'POST' });
      const body = await resp.json();
      if (body.status !== 'ok') {
        alert(`XRay tunnel ${action} failed: ${body.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`XRay tunnel ${action} failed: ${e}`);
    } finally {
      if (location.hash.replace('#', '') === '/') {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }
    }
  },

  // Format ISO-8601 created date as "ДД-ММ-ГГГГ, ЧЧ:ММ" (local time).
  _xrayFmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const p = (n) => String(n).padStart(2, '0');
    return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()}, `
         + `${p(d.getHours())}:${p(d.getMinutes())}`;
  },

  // Open a modal listing all XRay clients in a wide table — one row per
  // client with name, created date, VLESS+QR actions (links, not URLs),
  // per-direction traffic counters, and a revoke button. Fetches clients
  // and per-user stats in parallel so the table can be rendered in one
  // go.
  async _onXrayClientsClick(ev) {
    if (!ev.target.closest('[data-xray-clients]')) return;
    const [data, status] = await Promise.all([
      API.get('/xray/clients'),
      API.get('/xray/status'),
    ]);
    if (!data) return;

    // Per-user stats come keyed by xray's email ("<name>@vpngateway", see
    // vpngw-xray-render-config.py). Map by client name for easy lookup.
    const users = (status && status.stats && status.stats.users) || {};
    const statByName = {};
    for (const [email, st] of Object.entries(users)) {
      const name = String(email).split('@')[0];
      statByName[name] = st;
    }

    const rowsHtml = (data.clients || []).map((c) => {
      const st = statByName[c.name] || { uplink: 0, downlink: 0 };
      return `
        <tr data-uuid="${c.uuid}">
          <td class="xray-cell-name">${c.name || '(unnamed)'}</td>
          <td class="xray-cell-date">${this._xrayFmtDate(c.created)}</td>
          <td class="xray-cell-action">
            <a href="#" class="xray-link" data-xray-copy="${c.uuid}"
               title="Скопировать vless:// в буфер">VLESS</a>
          </td>
          <td class="xray-cell-action">
            <a href="#" class="xray-link" data-xray-qr="${c.uuid}"
               title="Показать QR-код">QR</a>
          </td>
          <td class="xray-cell-stat" title="downloaded by client">${formatBytes(st.downlink || 0)}</td>
          <td class="xray-cell-stat" title="sent by client">${formatBytes(st.uplink || 0)}</td>
          <td class="xray-cell-action">
            <button class="xray-revoke" data-xray-revoke="${c.uuid}"
                    title="Отозвать (удалить клиента)">&times;</button>
          </td>
        </tr>
      `;
    }).join('') || `
      <tr><td colspan="7" class="card-sub" style="text-align:center;padding:18px">
        нет клиентов
      </td></tr>
    `;

    showModal('XRay clients', `
      <div class="xray-clients-wrap">
        <table class="xray-clients-table">
          <thead>
            <tr>
              <th>Имя</th>
              <th>Создан</th>
              <th>Конфиг</th>
              <th>QR</th>
              <th title="что клиент скачал">↓ Скачано</th>
              <th title="что клиент отправил">↑ Отправлено</th>
              <th>Отозвать</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
      <hr style="margin:14px 0;border:none;border-top:1px solid var(--border)">
      <div style="display:flex;gap:8px;align-items:center">
        <input id="xrayNewName" placeholder="имя (a-z0-9_-, до 32 символов)"
               style="flex:1;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--text)">
        <button class="btn btn-primary" data-xray-add="1">+ Добавить клиента</button>
      </div>
      <div style="margin-top:12px;text-align:right">
        <button class="btn btn-ghost" onclick="window.closeModal()">Закрыть</button>
      </div>
    `);
  },

  // Click handlers inside the XRay-clients modal (delegated from the
  // modal element itself — simpler than rebinding on every refresh).
  async _onXrayModalClick(ev) {
    const copyBtn   = ev.target.closest('[data-xray-copy]');
    const qrBtn     = ev.target.closest('[data-xray-qr]');
    const revokeBtn = ev.target.closest('[data-xray-revoke]');
    const addBtn    = ev.target.closest('[data-xray-add]');

    // — VLESS link → fetch share-url, write to clipboard, toast.
    if (copyBtn) {
      ev.preventDefault();
      const uuid = copyBtn.dataset.xrayCopy;
      const data = await API.get('/xray/clients/' + uuid + '/share-url');
      if (!data || !data.share_url) return;
      try {
        await navigator.clipboard.writeText(data.share_url);
        Toast.show('vless:// скопирован в буфер', 'success');
      } catch (e) {
        // Fallback: show inline so user can long-press / select.
        Toast.show('Clipboard write blocked — open URL inline', 'error');
        const row = copyBtn.closest('tr');
        if (row) {
          const drop = document.createElement('tr');
          drop.className = 'xray-inline-drop';
          drop.innerHTML = `<td colspan="7"><textarea readonly rows="3"
              style="width:100%;font-family:ui-monospace,monospace;font-size:11px;
                     padding:6px;border-radius:4px;border:1px solid var(--border);
                     background:var(--bg);color:var(--text)">${data.share_url}</textarea></td>`;
          row.parentNode.insertBefore(drop, row.nextSibling);
        }
      }
      return;
    }

    // — QR link → fetch SVG and insert/remove inline below the row.
    if (qrBtn) {
      ev.preventDefault();
      const uuid = qrBtn.dataset.xrayQr;
      const row = qrBtn.closest('tr');
      if (!row) return;
      const next = row.nextElementSibling;
      // Toggle off if QR for this row is already showing.
      if (next && next.classList.contains('xray-qr-row')
              && next.dataset.uuid === uuid) {
        next.remove();
        return;
      }
      // Remove any other open QR/drop rows (one expansion at a time).
      document.querySelectorAll('.xray-qr-row, .xray-inline-drop').forEach(r => r.remove());
      const data = await API.get('/xray/clients/' + uuid + '/qr');
      if (!data || !data.svg) return;
      const tr = document.createElement('tr');
      tr.className = 'xray-qr-row';
      tr.dataset.uuid = uuid;
      tr.innerHTML = `<td colspan="7" class="xray-qr-cell">
        <div class="xray-qr-display">${data.svg}</div>
      </td>`;
      row.parentNode.insertBefore(tr, row.nextSibling);
      return;
    }

    // — Revoke → confirm → DELETE → remove row from DOM optimistically.
    if (revokeBtn) {
      ev.preventDefault();
      const uuid = revokeBtn.dataset.xrayRevoke;
      const row = revokeBtn.closest('tr');
      const name = row ? row.querySelector('.xray-cell-name')?.textContent : uuid;
      if (!confirmAction(`Отозвать клиента «${name}»? Активная сессия (если есть) будет разорвана.`)) return;

      // Optimistic UI — fade the row immediately, fully remove on success.
      if (row) row.style.opacity = '0.4';

      const resp = await fetch('/api/v1/xray/clients/' + uuid, { method: 'DELETE' });
      const body = await resp.json().catch(() => ({}));
      if (body.status !== 'ok') {
        if (row) row.style.opacity = '';
        Toast.show(`Не удалось отозвать: ${body.error || 'unknown'}`, 'error');
        return;
      }
      if (row) {
        // Also drop any expanded QR row that belongs to this client.
        const sib = row.nextElementSibling;
        if (sib && sib.classList.contains('xray-qr-row')
                && sib.dataset.uuid === uuid) sib.remove();
        row.remove();
      }
      Toast.show(`Клиент «${name}» отозван`, 'success');
      return;
    }

    // — Add client → POST, then append the new row in-place (no full
    // re-render, so VLESS/QR links of existing rows don't lose any open
    // expansions, and the user doesn't see a modal-flash).
    if (addBtn) {
      ev.preventDefault();
      const input = document.getElementById('xrayNewName');
      const name = (input && input.value || '').trim();
      if (!name) { Toast.show('Введите имя', 'error'); return; }
      const data = await API.post('/xray/clients', { name });
      if (!data || !data.client) return;

      const c = data.client;
      const tbody = document.querySelector('.xray-clients-table tbody');
      if (tbody) {
        // If the table was empty, the only row is the colspan=7
        // "нет клиентов" placeholder — drop it before appending.
        const placeholder = tbody.querySelector('td[colspan="7"]');
        if (placeholder) {
          const ph = placeholder.closest('tr');
          if (ph) ph.remove();
        }
        const tr = document.createElement('tr');
        tr.dataset.uuid = c.uuid;
        tr.innerHTML = `
          <td class="xray-cell-name">${c.name || '(unnamed)'}</td>
          <td class="xray-cell-date">${this._xrayFmtDate(c.created)}</td>
          <td class="xray-cell-action">
            <a href="#" class="xray-link" data-xray-copy="${c.uuid}"
               title="Скопировать vless:// в буфер">VLESS</a>
          </td>
          <td class="xray-cell-action">
            <a href="#" class="xray-link" data-xray-qr="${c.uuid}"
               title="Показать QR-код">QR</a>
          </td>
          <td class="xray-cell-stat" title="downloaded by client">${formatBytes(0)}</td>
          <td class="xray-cell-stat" title="sent by client">${formatBytes(0)}</td>
          <td class="xray-cell-action">
            <button class="xray-revoke" data-xray-revoke="${c.uuid}"
                    title="Отозвать (удалить клиента)">&times;</button>
          </td>
        `;
        tbody.appendChild(tr);
        // Scroll the new row into view inside the scrollable wrapper.
        const wrap = document.querySelector('.xray-clients-wrap');
        if (wrap) wrap.scrollTop = wrap.scrollHeight;
      }
      if (input) input.value = '';
      Toast.show(`Клиент «${name}» добавлен`, 'success');
      return;
    }
  },

  // Toggle handler — bound via the same delegated listener as the VPN
  // config picker (see mount()). Issues POST /openvpn/(enable|disable),
  // then forces a dashboard re-render so the user sees the new state
  // without waiting for the 10-second tick.
  async _onOvpnToggle(ev) {
    const btn = ev.target.closest('.ovpn-toggle');
    if (!btn || btn.classList.contains('busy')) return;
    const action = btn.dataset.action;
    if (action !== 'enable' && action !== 'disable') return;

    btn.classList.add('busy');
    try {
      const resp = await fetch(`/api/v1/openvpn/${action}`, { method: 'POST' });
      const body = await resp.json();
      if (body.status !== 'ok') {
        alert(`OpenVPN ${action} failed: ${body.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`OpenVPN ${action} failed: ${e}`);
    } finally {
      if (location.hash.replace('#', '') === '/') {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }
    }
  },

  // Toggle AmneziaWG service for the main split-tunnel. This only starts
  // or stops vpngw-vpn; routing mode, domain lists, dnsmasq, and OpenVPN
  // are left untouched so the Network card remains useful in direct mode.
  async _onVpnToggle(ev) {
    const btn = ev.target.closest('.vpn-toggle');
    if (!btn || btn.classList.contains('busy')) return;
    const action = btn.dataset.vpnAction;
    if (action !== 'start' && action !== 'stop') return;

    btn.classList.add('busy');
    try {
      const resp = await fetch(`/api/v1/vpn/${action}`, { method: 'POST' });
      const body = await resp.json();
      if (body.status !== 'ok') {
        alert(`VPN ${action} failed: ${body.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`VPN ${action} failed: ${e}`);
    } finally {
      if (location.hash.replace('#', '') === '/') {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }
    }
  },

  // Click on an OpenVPN config -> POST /openvpn/configs/{name}/activate.
  // If vpngw-openvpn is running, the backend restarts only that service;
  // if it is disabled, the selected name is persisted and used next enable.
  async _onOvpnConfigClick(ev) {
    const item = ev.target.closest('.ovpn-config');
    if (!item || item.classList.contains('active') || item.classList.contains('switching')) return;
    const name = item.dataset.ovpnConfig;
    if (!name) return;

    const picker = document.getElementById('ovpnConfigs');
    if (picker) picker.classList.add('switching');
    item.classList.add('switching');
    item.title = 'switching…';

    try {
      const resp = await fetch(`/api/v1/openvpn/configs/${encodeURIComponent(name)}/activate`, { method: 'POST' });
      const body = await resp.json();
      if (body.status !== 'ok') {
        alert(`OpenVPN switch failed: ${body.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`OpenVPN switch failed: ${e}`);
    } finally {
      if (location.hash.replace('#', '') === '/') {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }
    }
  },

  async _onXrayClientConfigClick(ev) {
    if (ev.target.closest('[data-xray-client-config-ping], [data-xray-client-config-hard-test], [data-xray-client-config-delete]')) return;
    const item = ev.target.closest('.xray-client-config');
    if (!item || item.classList.contains('active') || item.classList.contains('switching')) return;
    const name = item.dataset.xrayClientConfig;
    if (!name) return;

    const picker = document.getElementById('xrayClientConfigs');
    if (picker) picker.classList.add('switching');
    item.classList.add('switching');
    item.title = 'switching…';

    try {
      const resp = await fetch(`/api/v1/xray-client/configs/${encodeURIComponent(name)}/activate`, { method: 'POST' });
      const body = await resp.json();
      if (body.status !== 'ok') {
        alert(`XRay config switch failed: ${body.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`XRay config switch failed: ${e}`);
    } finally {
      if (location.hash.replace('#', '') === '/') {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }
    }
  },

  async _refreshDashboard() {
    if (location.hash.replace('#', '') !== '/') return;
    const html = await this.render();
    if (html) {
      document.getElementById('content').innerHTML = html;
      BandwidthChart.resize();
    }
  },

  async _onXrayGroupToggle(ev) {
    const btn = ev.target.closest('[data-xray-client-group-toggle]');
    if (!btn) return;
    const id = btn.dataset.xrayClientGroupToggle;
    if (!id) return;
    this.xrayExpandedGroups[id] = this.xrayExpandedGroups[id] === false;
    await this._refreshDashboard();
  },

  async _onXraySubscriptionAdd(ev) {
    if (!ev.target.closest('[data-xray-subscription-add]')) return;
    const name = window.prompt('Subscription name');
    if (!name) return;
    const url = window.prompt('Subscription URL');
    if (!url) return;
    const hwid = window.prompt('Optional X-HWID for device-bound providers; easy-api uses gateway HWID when empty');
    const payload = { name: name.trim(), url: url.trim() };
    if (hwid && hwid.trim()) payload.hwid = hwid.trim();
    const data = await API.post('/xray-client/subscriptions', payload);
    if (data) {
      this.xrayExpandedGroups[name.trim()] = true;
      const pruned = data.pruned_count ? `, pruned ${data.pruned_count}` : '';
      Toast.show(`Subscription added: ${data.generated_count || 0} configs${pruned}`);
      await this._refreshDashboard();
    }
  },

  async _onXrayConfigAdd(ev) {
    if (!ev.target.closest('[data-xray-config-add]')) return;
    ev.stopPropagation();
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.key,.json,text/plain,application/json';
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const defaultName = file.name.replace(/\.(key|json)$/i, '');
      const chosen = window.prompt('Config name', defaultName);
      if (!chosen) return;
      const name = chosen.trim().replace(/\.key$/i, '');
      const existing = this._xrayConfigNames().includes(name);
      const overwrite = existing && confirmAction(`Overwrite existing XRay config "${name}"?`);
      if (existing && !overwrite) return;
      const content = await file.text();
      const data = await API.post('/xray-client/configs', {
        name,
        filename: file.name,
        content,
        overwrite,
      });
      if (data) {
        this.xrayExpandedGroups.standalone = true;
        Toast.show(`${data.overwritten ? 'Updated' : 'Added'} XRay config: ${data.name}`);
        await this._refreshDashboard();
      }
    };
    input.click();
  },

  async _onXrayConfigDelete(ev) {
    const btn = ev.target.closest('[data-xray-client-config-delete]');
    if (!btn) return;
    ev.stopPropagation();
    const name = btn.dataset.xrayClientConfigDelete;
    if (!name) return;
    if (!confirmAction(`Delete standalone XRay config "${name}"?`)) return;
    btn.disabled = true;
    btn.textContent = '...';
    const data = await API.del(`/xray-client/configs/${encodeURIComponent(name)}`);
    if (data) {
      delete this.xrayPingResults[name];
      delete this.xrayHardTestResults[name];
      Toast.show(`XRay config deleted: ${name}`);
    }
    await this._refreshDashboard();
  },

  async _onXraySubscriptionRefresh(ev) {
    const btn = ev.target.closest('[data-xray-subscription-refresh]');
    if (!btn) return;
    const name = btn.dataset.xraySubscriptionRefresh;
    if (!name) return;
    btn.disabled = true;
    btn.textContent = '...';
    const data = await API.post(`/xray-client/subscriptions/${encodeURIComponent(name)}/refresh`);
    if (data) {
      const pruned = data.pruned_count ? `, pruned ${data.pruned_count}` : '';
      const active = data.removed_active ? ', active selector cleared' : '';
      const retained = data.retained_active ? `, active retained: ${data.retained_active}` : '';
      Toast.show(`Subscription refreshed: ${data.generated_count || 0} configs${pruned}${active}${retained}`);
    }
    await this._refreshDashboard();
  },

  async _onXraySubscriptionDelete(ev) {
    const btn = ev.target.closest('[data-xray-subscription-delete]');
    if (!btn) return;
    const name = btn.dataset.xraySubscriptionDelete;
    if (!name) return;
    if (!confirmAction(`Delete subscription "${name}" and its generated configs?`)) return;
    btn.disabled = true;
    btn.textContent = '...';
    const data = await API.del(`/xray-client/subscriptions/${encodeURIComponent(name)}`);
    if (data) {
      delete this.xrayExpandedGroups[name];
      const retained = data.retained_active ? `, active retained: ${data.retained_active}` : '';
      Toast.show(`Subscription deleted: ${data.removed_count || 0} configs removed${retained}`);
    }
    await this._refreshDashboard();
  },

  async _onXrayConfigPing(ev) {
    const btn = ev.target.closest('[data-xray-client-config-ping]');
    if (!btn) return;
    ev.stopPropagation();
    const name = btn.dataset.xrayClientConfigPing;
    if (!name) return;
    btn.disabled = true;
    btn.textContent = '...';
    const data = await this._runXrayConfigPing(name);
    const text = data.ok
      ? `${name}: ${data.time_ms} ms ${data.exit_ip || ''}`
      : `${name}: failed ${data.error || ''}`;
    Toast.show(text, data.ok ? 'success' : 'error', 7000);
    btn.disabled = false;
    btn.textContent = 'ping';
  },

  async _runXrayConfigPing(name) {
    document.querySelectorAll(`[data-xray-ping-result="${CSS.escape(name)}"]`).forEach(el => { el.textContent = '...'; });
    const data = await API.post(`/xray-client/configs/${encodeURIComponent(name)}/ping`);
    const result = data || { name, ok: false };
    this._setXrayPingResult(name, result);
    return result;
  },

  async _onXrayGroupPing(ev) {
    const btn = ev.target.closest('[data-xray-client-group-ping]');
    if (!btn) return;
    ev.stopPropagation();
    const groupId = btn.dataset.xrayClientGroupPing;
    if (!groupId) return;
    const names = this._xrayGroupConfigNames(groupId);
    if (!names.length) return;
    btn.disabled = true;
    btn.textContent = '...';
    let completed = 0;
    this._setXrayGroupPingResult(groupId, names, completed);
    await this._runXrayGroupWorkers(names, async (name) => {
      await this._runXrayConfigPing(name);
      completed += 1;
      this._setXrayGroupPingResult(groupId, names, completed);
    });
    const group = this.xrayGroupPingResults[groupId] || { okCount: 0, total: names.length };
    Toast.show(`${groupId}: ${group.okCount}/${names.length} ping OK`, group.okCount ? 'success' : 'error', 9000);
    btn.disabled = false;
    btn.textContent = 'ping';
  },

  async _onXrayConfigHardTest(ev) {
    const btn = ev.target.closest('[data-xray-client-config-hard-test]');
    if (!btn) return;
    ev.stopPropagation();
    const name = btn.dataset.xrayClientConfigHardTest;
    if (!name) return;
    btn.disabled = true;
    const ping = await this._runXrayConfigPing(name);
    if (!ping || !ping.ok) {
      this._setXrayHardTestResult(name, {
        name,
        ok: false,
        skipped: true,
        speed_bps: 0,
        speed_label: '0',
        error: 'ping failed; hard test skipped',
      });
      btn.disabled = false;
      Toast.show(`${name}: ping n/a, hard test skipped`, 'error', 9000);
      return;
    }
    this._setXrayHardTestRunning(name, true);
    const data = await API.post(`/xray-client/configs/${encodeURIComponent(name)}/hard-test?skip_ping=1`);
    this._setXrayHardTestResult(name, data || { name, ok: false, speed_bps: 0, speed_label: '0' });
    btn.disabled = false;
    const result = this.xrayHardTestResults[name];
    Toast.show(
      result.ok ? `${name}: ${result.speed_label}` : `${name}: hard test failed`,
      result.ok ? 'success' : 'error',
      9000
    );
  },

  async _onXrayGroupHardTest(ev) {
    const btn = ev.target.closest('[data-xray-client-group-hard-test]');
    if (!btn) return;
    ev.stopPropagation();
    const groupId = btn.dataset.xrayClientGroupHardTest;
    if (!groupId) return;
    const names = this._xrayGroupConfigNames(groupId);
    if (!names.length) return;
    btn.disabled = true;
    let completed = 0;
    this._setXrayGroupHardTestResult(groupId, names, completed);
    await this._runXrayGroupWorkers(names, async (name) => {
      const ping = await this._runXrayConfigPing(name);
      if (!ping || !ping.ok) {
        this._setXrayHardTestResult(name, {
          name,
          ok: false,
          skipped: true,
          speed_bps: 0,
          speed_label: '0',
          error: 'ping failed; hard test skipped',
        });
        completed += 1;
        this._setXrayGroupHardTestResult(groupId, names, completed);
        return;
      }
      this._setXrayHardTestRunning(name, true);
      const data = await API.post(`/xray-client/configs/${encodeURIComponent(name)}/hard-test?skip_ping=1`);
      this._setXrayHardTestResult(name, data || { name, ok: false, speed_bps: 0, speed_label: '0' });
      completed += 1;
      this._setXrayGroupHardTestResult(groupId, names, completed);
    });
    const group = this.xrayGroupHardTestResults[groupId] || { okCount: 0, total: names.length };
    Toast.show(`${groupId}: ${group.okCount}/${names.length} hard tests OK`, group.okCount ? 'success' : 'error', 9000);
    btn.disabled = false;
  },

  async _onAmneziaConfigAdd(ev) {
    if (!ev.target.closest('[data-amnezia-config-add]')) return;
    ev.stopPropagation();
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.conf,text/plain';
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const defaultName = file.name.replace(/\.conf$/i, '');
      const chosen = window.prompt('Config name', defaultName);
      if (!chosen) return;
      const name = chosen.trim().replace(/\.conf$/i, '');
      const existing = this._amneziaConfigNames().includes(name);
      const overwrite = existing && confirmAction(`Overwrite existing Amnezia config "${name}"?`);
      if (existing && !overwrite) return;
      const content = await file.text();
      const data = await API.post('/vpn/configs', {
        name,
        filename: file.name,
        content,
        overwrite,
      });
      if (data) {
        Toast.show(`${data.overwritten ? 'Updated' : 'Added'} Amnezia config: ${data.name}`);
        await this._refreshDashboard();
      }
    };
    input.click();
  },

  async _onAmneziaConfigDelete(ev) {
    const btn = ev.target.closest('[data-amnezia-config-delete]');
    if (!btn) return;
    ev.stopPropagation();
    const name = btn.dataset.amneziaConfigDelete;
    if (!name) return;
    if (!confirmAction(`Delete Amnezia config "${name}"?`)) return;
    btn.disabled = true;
    btn.textContent = '...';
    const data = await API.del(`/vpn/configs/${encodeURIComponent(name)}`);
    if (data) {
      delete this.amneziaPingResults[name];
      delete this.amneziaHardTestResults[name];
      Toast.show(`Amnezia config deleted: ${name}`);
    }
    await this._refreshDashboard();
  },

  async _runAmneziaConfigPing(name) {
    document.querySelectorAll(`[data-amnezia-ping-result="${CSS.escape(name)}"]`).forEach(el => { el.textContent = '...'; });
    const data = await API.post(`/vpn/configs/${encodeURIComponent(name)}/ping`);
    const result = data || { name, ok: false };
    this._setAmneziaPingResult(name, result);
    return result;
  },

  async _onAmneziaConfigPing(ev) {
    const btn = ev.target.closest('[data-amnezia-config-ping]');
    if (!btn) return;
    ev.stopPropagation();
    const name = btn.dataset.amneziaConfigPing;
    if (!name) return;
    btn.disabled = true;
    btn.textContent = '...';
    const data = await this._runAmneziaConfigPing(name);
    const text = data.ok
      ? `${name}: ${data.time_ms} ms`
      : `${name}: failed ${data.error || ''}`;
    Toast.show(text, data.ok ? 'success' : 'error', 7000);
    btn.disabled = false;
    btn.textContent = 'ping';
  },

  async _onAmneziaGroupPing(ev) {
    const btn = ev.target.closest('[data-amnezia-group-ping]');
    if (!btn) return;
    ev.stopPropagation();
    const groupId = btn.dataset.amneziaGroupPing || 'all';
    const names = this._amneziaConfigNames();
    if (!names.length) return;
    btn.disabled = true;
    btn.textContent = '...';
    let completed = 0;
    this._setAmneziaGroupPingResult(groupId, names, completed);
    await this._runXrayGroupWorkers(names, async (name) => {
      await this._runAmneziaConfigPing(name);
      completed += 1;
      this._setAmneziaGroupPingResult(groupId, names, completed);
    });
    const group = this.amneziaGroupPingResults[groupId] || { okCount: 0, total: names.length };
    Toast.show(`Amnezia: ${group.okCount}/${names.length} ping OK`, group.okCount ? 'success' : 'error', 9000);
    btn.disabled = false;
    btn.textContent = 'ping';
  },

  async _onAmneziaConfigHardTest(ev) {
    const btn = ev.target.closest('[data-amnezia-config-hard-test]');
    if (!btn) return;
    ev.stopPropagation();
    const name = btn.dataset.amneziaConfigHardTest;
    if (!name) return;
    btn.disabled = true;
    const ping = await this._runAmneziaConfigPing(name);
    if (!ping || !ping.ok) {
      this._setAmneziaHardTestResult(name, {
        name,
        ok: false,
        skipped: true,
        speed_bps: 0,
        speed_label: '0',
        error: 'ping failed; hard test skipped',
      });
      btn.disabled = false;
      Toast.show(`${name}: ping n/a, hard test skipped`, 'error', 9000);
      return;
    }
    this._setAmneziaHardTestRunning(name, true);
    const data = await API.post(`/vpn/configs/${encodeURIComponent(name)}/hard-test?skip_ping=1`);
    this._setAmneziaHardTestResult(name, data || { name, ok: false, speed_bps: 0, speed_label: '0' });
    btn.disabled = false;
    const result = this.amneziaHardTestResults[name];
    Toast.show(
      result.ok ? `${name}: ${result.speed_label}` : `${name}: hard test failed`,
      result.ok ? 'success' : 'error',
      9000
    );
  },

  async _onAmneziaGroupHardTest(ev) {
    const btn = ev.target.closest('[data-amnezia-group-hard-test]');
    if (!btn) return;
    ev.stopPropagation();
    const groupId = btn.dataset.amneziaGroupHardTest || 'all';
    const names = this._amneziaConfigNames();
    if (!names.length) return;
    btn.disabled = true;
    let completed = 0;
    this._setAmneziaGroupHardTestResult(groupId, names, completed);
    await this._runXrayGroupWorkers(names, async (name) => {
      const ping = await this._runAmneziaConfigPing(name);
      if (!ping || !ping.ok) {
        this._setAmneziaHardTestResult(name, {
          name,
          ok: false,
          skipped: true,
          speed_bps: 0,
          speed_label: '0',
          error: 'ping failed; hard test skipped',
        });
        completed += 1;
        this._setAmneziaGroupHardTestResult(groupId, names, completed);
        return;
      }
      this._setAmneziaHardTestRunning(name, true);
      const data = await API.post(`/vpn/configs/${encodeURIComponent(name)}/hard-test?skip_ping=1`);
      this._setAmneziaHardTestResult(name, data || { name, ok: false, speed_bps: 0, speed_label: '0' });
      completed += 1;
      this._setAmneziaGroupHardTestResult(groupId, names, completed);
    });
    const group = this.amneziaGroupHardTestResults[groupId] || { okCount: 0, total: names.length };
    Toast.show(`Amnezia: ${group.okCount}/${names.length} hard tests OK`, group.okCount ? 'success' : 'error', 9000);
    btn.disabled = false;
  },

  // Click on a config row -> POST /vpn/configs/{name}/activate.
  // Uses event delegation so the handler survives full re-renders of the
  // dashboard content. Disables further clicks while a switch is in flight.
  async _onConfigClick(ev) {
    if (ev.target.closest('button')) return;
    const item = ev.target.closest('.vpn-config');
    if (!item || item.classList.contains('active') || item.classList.contains('switching')) return;
    const name = item.dataset.config;
    if (!name) return;

    // Lock the whole picker so multiple switches can't race.
    const picker = document.getElementById('vpnConfigs');
    if (picker) picker.classList.add('switching');
    item.classList.add('switching');
    item.title = 'switching…';

    try {
      const resp = await fetch(`/api/v1/vpn/configs/${encodeURIComponent(name)}/activate`, { method: 'POST' });
      const body = await resp.json();
      if (body.status !== 'ok') {
        alert(`Switch failed: ${body.error || 'unknown error'}`);
      }
    } catch (e) {
      alert(`Switch failed: ${e}`);
    } finally {
      // Force an immediate dashboard re-render — the periodic timer
      // would otherwise leave the user staring at the previous flag
      // for up to 10s.
      if (location.hash.replace('#', '') === '/') {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }
    }
  },

  mount() {
    BandwidthChart.init();
    if (this.isReadOnly()) {
      this.timer = setInterval(async () => {
        const html = await this.render();
        if (html) {
          document.getElementById('content').innerHTML = html;
          BandwidthChart.resize();
        }
      }, 10000);
      return;
    }
    // Single delegated listener — the markup gets replaced wholesale
    // every 10s, so binding directly on .vpn-config elements would be
    // pointless.
    this._clickHandler = (ev) => {
      if (ev.target.closest('[data-xray-action]')) {
        this._onXrayToggle(ev);
      } else if (ev.target.closest('[data-xray-client-action]')) {
        this._onXrayClientToggle(ev);
      } else if (ev.target.closest('[data-xray-clients]')) {
        this._onXrayClientsClick(ev);
      } else if (ev.target.closest('.vpn-toggle')) {
        this._onVpnToggle(ev);
      } else if (ev.target.closest('.ovpn-toggle')) {
        this._onOvpnToggle(ev);
      } else if (ev.target.closest('.ovpn-config')) {
        this._onOvpnConfigClick(ev);
      } else if (ev.target.closest('[data-amnezia-config-add]')) {
        this._onAmneziaConfigAdd(ev);
      } else if (ev.target.closest('[data-amnezia-config-delete]')) {
        this._onAmneziaConfigDelete(ev);
      } else if (ev.target.closest('[data-amnezia-group-ping]')) {
        this._onAmneziaGroupPing(ev);
      } else if (ev.target.closest('[data-amnezia-group-hard-test]')) {
        this._onAmneziaGroupHardTest(ev);
      } else if (ev.target.closest('[data-amnezia-config-ping]')) {
        this._onAmneziaConfigPing(ev);
      } else if (ev.target.closest('[data-amnezia-config-hard-test]')) {
        this._onAmneziaConfigHardTest(ev);
      } else if (ev.target.closest('[data-xray-config-add]')) {
        this._onXrayConfigAdd(ev);
      } else if (ev.target.closest('[data-xray-client-config-delete]')) {
        this._onXrayConfigDelete(ev);
      } else if (ev.target.closest('[data-xray-subscription-add]')) {
        this._onXraySubscriptionAdd(ev);
      } else if (ev.target.closest('[data-xray-subscription-delete]')) {
        this._onXraySubscriptionDelete(ev);
      } else if (ev.target.closest('[data-xray-subscription-refresh]')) {
        this._onXraySubscriptionRefresh(ev);
      } else if (ev.target.closest('[data-xray-client-group-ping]')) {
        this._onXrayGroupPing(ev);
      } else if (ev.target.closest('[data-xray-client-group-hard-test]')) {
        this._onXrayGroupHardTest(ev);
      } else if (ev.target.closest('[data-xray-client-group-toggle]')) {
        this._onXrayGroupToggle(ev);
      } else if (ev.target.closest('[data-xray-client-config-ping]')) {
        this._onXrayConfigPing(ev);
      } else if (ev.target.closest('[data-xray-client-config-hard-test]')) {
        this._onXrayConfigHardTest(ev);
      } else if (ev.target.closest('.xray-client-config')) {
        this._onXrayClientConfigClick(ev);
      } else if (ev.target.closest('.vpn-config')) {
        this._onConfigClick(ev);
      }
    };
    document.getElementById('content').addEventListener('click', this._clickHandler);

    // The XRay-clients modal lives in #modal, which is OUTSIDE #content
    // — bind its delegated listener separately so clicks inside it work
    // even when dashboard re-renders rip out #content's children.
    this._modalHandler = (ev) => this._onXrayModalClick(ev);
    document.getElementById('modal').addEventListener('click', this._modalHandler);

    this.timer = setInterval(async () => {
      const html = await this.render();
      if (html && location.hash.replace('#', '') === '/') {
        document.getElementById('content').innerHTML = html;
        BandwidthChart.resize();
      }
    }, 10000);
  },

  unmount() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    if (this._clickHandler) {
      const c = document.getElementById('content');
      if (c) c.removeEventListener('click', this._clickHandler);
      this._clickHandler = null;
    }
    if (this._modalHandler) {
      const m = document.getElementById('modal');
      if (m) m.removeEventListener('click', this._modalHandler);
      this._modalHandler = null;
    }
    BandwidthChart.destroy();
  }
};
