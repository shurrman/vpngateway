/* Services management page */

const ServicesPage = {
  timer: null,

  async render() {
    const data = await API.get('/services');
    if (!data) return '<div class="loading">Failed to load</div>';

    return `
      <div class="page-header">
        <h1 class="page-title">Services</h1>
      </div>
      <div class="card-grid" style="grid-template-columns:1fr">
        ${data.services.map(s => `
          <div class="card">
            <div class="service-card">
              <span class="status-dot ${s.active ? 'up' : 'down'}"></span>
              <div class="service-info">
                <div class="service-name">${Toast.escape(s.name)}</div>
                <div class="service-state">${Toast.escape(s.state)} ${s.enabled ? '' : '(disabled)'}</div>
                ${s.description ? `<div class="service-state">${Toast.escape(s.description)}</div>` : ''}
              </div>
              <div class="service-actions">
                ${s.active
                  ? `<button class="btn btn-ghost btn-sm" onclick="ServicesPage.action('${s.name}','restart')">Restart</button>
                     <button class="btn btn-danger btn-sm" onclick="ServicesPage.action('${s.name}','stop')">Stop</button>`
                  : `<button class="btn btn-primary btn-sm" onclick="ServicesPage.action('${s.name}','start')">Start</button>`
                }
                <button class="btn btn-ghost btn-sm" onclick="ServicesPage.showLogs('${s.name}')">Logs</button>
              </div>
            </div>
            <div id="logs-${s.name}"></div>
          </div>
        `).join('')}
      </div>
    `;
  },

  async action(name, act) {
    if (act === 'stop' && !confirmAction(`Stop ${name}?`)) return;
    await API.post(`/services/${name}/${act}`);
    App.navigate(location.hash);
  },

  async showLogs(name) {
    const el = document.getElementById(`logs-${name}`);
    if (el.innerHTML) { el.innerHTML = ''; return; }
    const data = await API.get(`/services/${name}/logs?lines=100`);
    if (!data) return;
    el.innerHTML = `<div class="log-panel">${Toast.escape(data.logs)}</div>`;
  },

  mount() {
    this.timer = setInterval(async () => {
      if (location.hash.replace('#', '') === '/services') {
        const html = await this.render();
        if (html) document.getElementById('content').innerHTML = html;
      }
    }, 15000);
  },

  unmount() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
  }
};
