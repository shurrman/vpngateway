/* Routing state viewer page */

const RoutingPage = {
  activeTab: 'rules',

  currentMode: 'split',

  async render() {
    const modeData = await API.get('/routing/mode');
    if (modeData) this.currentMode = modeData.mode;

    const modeBtn = (mode, label) => {
      const active = this.currentMode === mode;
      return `<button class="btn ${active ? 'btn-primary' : 'btn-ghost'}" onclick="RoutingPage.setMode('${mode}')" ${active ? 'disabled' : ''}>${label}</button>`;
    };

    return `
      <div class="page-header">
        <h1 class="page-title">Routing</h1>
        <div class="btn-group">
          <button class="btn btn-ghost btn-sm" onclick="RoutingPage.setup()">Setup</button>
          <button class="btn btn-ghost btn-sm" onclick="RoutingPage.fixAmnezia()">Fix Amnezia</button>
          <button class="btn btn-danger btn-sm" onclick="RoutingPage.teardown()">Teardown</button>
        </div>
      </div>

      <div class="card" style="margin-bottom:20px">
        <div class="card-title">Routing Mode</div>
        <div class="btn-group">
          ${modeBtn('split', 'Split Tunneling')}
          ${modeBtn('all-vpn', 'All VPN')}
          ${modeBtn('all-direct', 'All Direct')}
        </div>
        <div class="card-sub" style="margin-top:8px">${this.modeDescription()}</div>
      </div>
      <div class="tabs">
        <div class="tab ${this.activeTab === 'rules' ? 'active' : ''}" onclick="RoutingPage.switchTab('rules')">IP Rules</div>
        <div class="tab ${this.activeTab === 'routes' ? 'active' : ''}" onclick="RoutingPage.switchTab('routes')">Routes</div>
        <div class="tab ${this.activeTab === 'ipset' ? 'active' : ''}" onclick="RoutingPage.switchTab('ipset')">IPSet</div>
      </div>
      <div id="tabContent">${await this.renderTab()}</div>
    `;
  },

  async renderTab() {
    if (this.activeTab === 'rules') return this.renderRules();
    if (this.activeTab === 'routes') return this.renderRoutes();
    if (this.activeTab === 'ipset') return this.renderIpset();
  },

  async renderRules() {
    const data = await API.get('/routing/rules');
    if (!data) return '';
    return `<div class="table-wrap"><table>
      <thead><tr><th>Priority</th><th>Selector</th><th>Action</th></tr></thead>
      <tbody>${data.rules.map(r => `
        <tr><td>${r.priority}</td><td style="font-family:var(--mono)">${Toast.escape(r.selector)}</td><td style="font-family:var(--mono)">${Toast.escape(r.action)}</td></tr>
      `).join('')}</tbody>
    </table></div>`;
  },

  async renderRoutes() {
    const data = await API.get('/routing/tables');
    if (!data) return '';
    const renderTable = (name, routes) => `
      <h3 style="font-size:14px;color:var(--accent);margin-bottom:8px">${name}</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>Destination</th><th>Gateway</th><th>Device</th></tr></thead>
        <tbody>${routes.map(r => `
          <tr>
            <td style="font-family:var(--mono)">${Toast.escape(r.destination)}</td>
            <td style="font-family:var(--mono)">${r.gateway || '—'}</td>
            <td>${r.device}</td>
          </tr>
        `).join('')}</tbody>
      </table></div>
    `;
    return renderTable('Main Table', data.main) + renderTable('Table 100 (VPN)', data.table_100);
  },

  async renderIpset() {
    const data = await API.get('/routing/ipset');
    if (!data) return '';
    return `
      <div class="card-grid">
        <div class="card">
          <div class="card-title">vpn_domains</div>
          <div class="card-value">${data.entries}</div>
          <div class="card-sub">of ${data.max_entries} max &middot; ${formatBytes(data.memory_bytes)} memory</div>
        </div>
        <div class="card">
          <div class="card-title">Test IP</div>
          <div style="display:flex;gap:8px">
            <input id="testIp" placeholder="8.8.8.8" style="flex:1" onkeydown="if(event.key==='Enter')RoutingPage.testIp()">
            <button class="btn btn-primary" onclick="RoutingPage.testIp()">Test</button>
          </div>
          <div id="ipTestResult"></div>
        </div>
      </div>
    `;
  },

  async testIp() {
    const ip = document.getElementById('testIp').value.trim();
    if (!ip) return;
    const data = await API.get(`/routing/ipset/test/${ip}`);
    const el = document.getElementById('ipTestResult');
    if (!data) { el.innerHTML = ''; return; }
    el.innerHTML = `<span class="inline-result ${data.in_set ? 'ok' : 'fail'}" style="margin-top:8px;display:inline-flex">
      ${ip}: ${data.in_set ? 'IN VPN set' : 'NOT in set'}
    </span>`;
  },

  async switchTab(tab) {
    this.activeTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.textContent.toLowerCase().includes(tab)));
    document.getElementById('tabContent').innerHTML = await this.renderTab();
  },

  modeDescription() {
    const desc = {
      'split': 'Only selected domains/IPs route through VPN. Everything else goes direct.',
      'all-vpn': 'ALL traffic routes through VPN tunnel. Full anonymity mode.',
      'all-direct': 'ALL traffic goes direct, bypassing VPN completely.',
    };
    return desc[this.currentMode] || '';
  },

  async setMode(mode) {
    const labels = { 'split': 'Split Tunneling', 'all-vpn': 'All VPN', 'all-direct': 'All Direct' };
    if (!confirmAction(`Switch to ${labels[mode]}?`)) return;
    await API.post('/routing/mode', { mode });
    App.navigate(location.hash);
  },

  async setup() { await API.post('/routing/setup'); },
  async teardown() {
    if (!confirmAction('Teardown will disable all VPN routing. Continue?')) return;
    await API.post('/routing/teardown');
  },
  async fixAmnezia() { await API.post('/routing/fix-amnezia'); },

  mount() {},
  unmount() {},
};
