/* Current LAN hosts and non-persistent gateway access control. */

const HostsPage = {
  refreshTimer: null,

  rows(hosts) {
    return hosts.map(host => {
      const allowed = host.vpn_allowed !== false;
      const ip = Toast.escape(host.ip);
      return `
        <tr>
          <td class="host-ip">${ip}</td>
          <td>${Toast.escape(host.hostname || '—')}</td>
          <td class="host-mac">${Toast.escape(host.mac || '—')}</td>
          <td class="host-device">${Toast.escape(host.device || 'Pending…')}</td>
          <td class="host-access-cell">
            <button
              class="host-access-toggle ${allowed ? 'on' : 'off'}"
              data-ip="${ip}"
              aria-pressed="${allowed}"
              aria-label="${allowed ? 'Disable' : 'Enable'} gateway access for ${ip}"
              onclick="HostsPage.setAccess('${ip}', ${!allowed}, this)">
              <span class="host-toggle-track"><span class="host-toggle-dot"></span></span>
              <span class="host-toggle-label">${allowed ? 'Allowed' : 'Local only'}</span>
            </button>
          </td>
        </tr>`;
    }).join('');
  },

  async render() {
    const data = await API.get('/hosts');
    if (!data) return '<div class="loading">Failed to load hosts</div>';
    return `
      <div class="page-header">
        <div>
          <h1 class="page-title">Hosts</h1>
          <div class="page-subtitle">Hosts with forwarded traffic during the last 15 minutes. Access decisions reset to Allowed after gateway or API restart.</div>
        </div>
        <button class="btn btn-ghost" onclick="HostsPage.refresh()">Refresh</button>
      </div>
      <div class="card hosts-card">
        <div class="table-wrap">
          <table class="hosts-table">
            <thead><tr><th>IP</th><th>Hostname</th><th>MAC</th><th>OS / Device</th><th>VPNGateway access</th></tr></thead>
            <tbody id="hostsTableBody">
              ${this.rows(data.hosts || []) || '<tr><td colspan="5" class="hosts-empty">No active LAN hosts found</td></tr>'}
            </tbody>
          </table>
        </div>
        <div class="hosts-note">Local only keeps RFC1918/private networks reachable and rejects other forwarded traffic. Access to the gateway itself is unchanged.</div>
      </div>`;
  },

  async refresh() {
    const body = document.getElementById('hostsTableBody');
    if (!body) return;
    const data = await API.get('/hosts');
    if (!data || !document.getElementById('hostsTableBody')) return;
    body.innerHTML = this.rows(data.hosts || []) || '<tr><td colspan="5" class="hosts-empty">No active LAN hosts found</td></tr>';
  },

  async setAccess(ip, enabled, button) {
    button.classList.add('busy');
    const host = await API.put(`/hosts/${encodeURIComponent(ip)}/access`, { enabled });
    if (!host) {
      button.classList.remove('busy');
      return;
    }
    const allowed = host.vpn_allowed !== false;
    button.classList.toggle('on', allowed);
    button.classList.toggle('off', !allowed);
    button.classList.remove('busy');
    button.setAttribute('aria-pressed', String(allowed));
    button.setAttribute('aria-label', `${allowed ? 'Disable' : 'Enable'} gateway access for ${ip}`);
    button.querySelector('.host-toggle-label').textContent = allowed ? 'Allowed' : 'Local only';
    button.setAttribute('onclick', `HostsPage.setAccess('${ip}', ${!allowed}, this)`);
  },

  mount() {
    this.refreshTimer = setInterval(() => this.refresh(), 15000);
  },

  unmount() {
    if (this.refreshTimer) clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  },
};
