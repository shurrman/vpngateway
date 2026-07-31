/* Notifications settings page */

const NotificationsPage = {
  async render() {
    const [config, status] = await Promise.all([
      API.get('/notifications/config'),
      API.get('/notifications/status'),
    ]);

    const c = config || {};
    const state = status ? status.state : 'unknown';
    const stateColor = state === 'OK' ? 'var(--green)' : state === 'PROBLEM' ? 'var(--red)' : 'var(--text-dim)';

    return `
      <div class="page-header">
        <h1 class="page-title">Notifications</h1>
        <div class="status">
          <span class="status-dot" style="background:${stateColor};box-shadow:0 0 6px ${stateColor}"></span>
          <span style="font-size:14px">Health: ${state}</span>
        </div>
      </div>

      <div class="card-grid" style="grid-template-columns:1fr">
        <div class="card">
          <div class="card-title">SMTP Settings</div>

          <div class="form-group">
            <label class="form-label">SMTP Host</label>
            <input id="smtpHost" value="${Toast.escape(c.smtp_host || 'smtp.gmail.com')}">
          </div>

          <div class="form-group">
            <label class="form-label">SMTP Port</label>
            <input id="smtpPort" type="number" value="${c.smtp_port || 587}">
          </div>

          <div class="form-group">
            <label class="form-label">SMTP User (email)</label>
            <input id="smtpUser" value="${Toast.escape(c.smtp_user || '')}" placeholder="user@gmail.com">
          </div>

          <div class="form-group">
            <label class="form-label">SMTP Password ${c.smtp_password_set ? '(set, leave empty to keep)' : ''}</label>
            <input id="smtpPassword" type="password" placeholder="${c.smtp_password_set ? '********' : 'App password'}">
          </div>

          <div class="form-group">
            <label class="form-label">From (optional, defaults to SMTP user)</label>
            <input id="smtpFrom" value="${Toast.escape(c.smtp_from || '')}">
          </div>

          <div class="form-group">
            <label class="form-label">Recipient Email</label>
            <input id="recipient" value="${Toast.escape(c.recipient || '')}" placeholder="admin@example.com">
          </div>

          <div class="form-group" style="display:flex;align-items:center;gap:10px">
            <input id="enabled" type="checkbox" style="width:auto" ${c.enabled ? 'checked' : ''}>
            <label for="enabled" style="font-size:13px;cursor:pointer">Enable email notifications</label>
          </div>

          <div class="btn-group" style="margin-top:16px">
            <button class="btn btn-primary" onclick="NotificationsPage.save()">Save Settings</button>
            <button class="btn btn-ghost" onclick="NotificationsPage.test()">Send Test Email</button>
          </div>
        </div>
      </div>
    `;
  },

  async save() {
    const config = {
      smtp_host: document.getElementById('smtpHost').value.trim(),
      smtp_port: parseInt(document.getElementById('smtpPort').value) || 587,
      smtp_user: document.getElementById('smtpUser').value.trim(),
      smtp_password: document.getElementById('smtpPassword').value,
      smtp_from: document.getElementById('smtpFrom').value.trim(),
      recipient: document.getElementById('recipient').value.trim(),
      enabled: document.getElementById('enabled').checked,
    };
    await API.put('/notifications/config', config);
    Toast.show('Settings saved', 'success');
  },

  async test() {
    const data = await API.post('/notifications/test');
    if (data && data.sent) {
      Toast.show('Test email sent successfully', 'success');
    }
  },

  mount() {},
  unmount() {},
};
