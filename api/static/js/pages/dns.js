/* DNS configuration and query page */

const DnsPage = {
  async render() {
    const config = await API.get('/dns/config');
    if (!config) return '<div class="loading">Failed to load</div>';

    return `
      <div class="page-header">
        <h1 class="page-title">DNS</h1>
        <button class="btn btn-ghost" onclick="DnsPage.flush()">Flush Cache</button>
      </div>

      <div class="card-grid">
        <div class="card">
          <div class="card-title">Upstream Servers</div>
          ${config.upstream_servers.map(s => `
            <div style="font-family:var(--mono);font-size:13px;padding:3px 0">${Toast.escape(s)}</div>
          `).join('')}
        </div>

        <div class="card">
          <div class="card-title">Local Zones</div>
          ${config.local_zones.map(z => `
            <div style="font-size:13px;padding:3px 0">
              <strong>.${Toast.escape(z.zone)}</strong> &rarr; ${Toast.escape(z.server)}
            </div>
          `).join('')}
        </div>

        <div class="card">
          <div class="card-title">Settings</div>
          <div style="font-size:13px">Cache size: <strong>${config.cache_size}</strong></div>
          <div style="font-size:13px;margin-top:4px">Listen: <code>${config.listen_addresses.join(', ')}</code></div>
        </div>
      </div>

      <div class="card" style="margin-top:16px">
        <div class="card-title">DNS Query Tool</div>
        <div style="display:flex;gap:8px;margin-bottom:12px">
          <input id="dnsQueryDomain" placeholder="youtube.com" style="flex:1" onkeydown="if(event.key==='Enter')DnsPage.query()">
          <select id="dnsQueryType" style="width:80px">
            <option>A</option>
            <option>AAAA</option>
            <option>CNAME</option>
            <option>MX</option>
            <option>TXT</option>
          </select>
          <button class="btn btn-primary" onclick="DnsPage.query()">Query</button>
        </div>
        <div id="dnsResult"></div>
      </div>
    `;
  },

  async query() {
    const domain = document.getElementById('dnsQueryDomain').value.trim();
    const type = document.getElementById('dnsQueryType').value;
    if (!domain) return;

    const data = await API.post('/dns/query', { domain, type });
    const el = document.getElementById('dnsResult');
    if (!data) { el.innerHTML = '<span class="inline-result fail">Error</span>'; return; }

    if (data.records.length === 0) {
      el.innerHTML = '<span class="inline-result fail">No records</span>';
    } else {
      el.innerHTML = `<div class="log-panel" style="max-height:200px">${data.records.map(r => Toast.escape(r)).join('\n')}</div>`;
    }
  },

  async flush() {
    if (!confirmAction('Restart dnsmasq and flush DNS cache?')) return;
    await API.post('/dns/flush');
  },

  mount() {},
  unmount() {},
};
