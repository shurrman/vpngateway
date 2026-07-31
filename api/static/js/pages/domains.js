/* Domains management page — one section per file in config/domains/
   (main.lst, aws.lst, cloudflare.lst, ...). All categories share the
   same vpn_domains ipset; the split is purely organisational. */

const DomainsPage = {
  // Last `category id` selected in the Add/Raw dialogs, persisted across
  // re-renders so the user doesn't have to re-pick it for each domain.
  lastCategory: 'main',

  async render() {
    const data = await API.get('/domains');
    if (!data) return '<div class="loading">Failed to load</div>';

    // Backwards compat: tolerate the old shape if a stale API somehow
    // ships {groups, raw} instead of {categories: [...]}.
    const categories = data.categories || (data.groups
      ? [{ id: 'main', filename: 'main.lst', total: data.total,
           groups: data.groups, raw: data.raw }]
      : []);

    const sectionsHtml = categories.map(cat => {
      const title = `${cat.id === 'main' ? 'Main' : cat.id.toUpperCase()} `
                  + `<span style="opacity:0.55;font-weight:400">`
                  + `${Toast.escape(cat.filename)} · ${cat.total}</span>`;
      const groupsHtml = cat.groups.map(g => `
        <div class="group-section">
          <button class="group-title domain-group-toggle" type="button"
                  aria-expanded="false"
                  onclick="DomainsPage.toggleGroup(this)">
            <span class="domain-group-caret" aria-hidden="true">&#8250;</span>
            <span>${Toast.escape(g.name)}</span>
            <span class="domain-group-count">${g.domains.length}</span>
          </button>
          <div class="domain-group-body" hidden>
            <table>
              <tbody>
                ${g.domains.map(d => `
                  <tr>
                    <td style="font-family:var(--mono)">${Toast.escape(d)}</td>
                    <td style="width:160px;text-align:right">
                      <button class="btn btn-ghost btn-sm"
                              onclick="DomainsPage.check('${Toast.escape(d)}', this)">Check</button>
                      <button class="btn btn-danger btn-sm btn-icon"
                              onclick="DomainsPage.remove('${Toast.escape(d)}', '${Toast.escape(cat.id)}')">&times;</button>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `).join('');

      return `
        <div class="domain-category" data-cat="${Toast.escape(cat.id)}">
          <div class="category-header" style="display:flex;align-items:baseline;gap:12px;margin:24px 0 8px">
            <h2 style="font-size:18px;margin:0">${title}</h2>
            <button class="btn btn-ghost btn-sm"
                    onclick="DomainsPage.showRawEditor('${Toast.escape(cat.id)}')">Raw editor</button>
          </div>
          ${groupsHtml || '<div class="card-sub" style="opacity:0.5">empty</div>'}
        </div>
      `;
    }).join('');

    return `
      <div class="page-header">
        <h1 class="page-title">Domains (${data.total})</h1>
        <div class="btn-group">
          <button class="btn btn-ghost" onclick="DomainsPage.showCheckDialog()">Check Domain</button>
          <button class="btn btn-ghost" onclick="DomainsPage.showRawCategoryDialog()">Raw editor</button>
          <button class="btn btn-primary" onclick="DomainsPage.showAddDialog()">+ Add Domain</button>
        </div>
      </div>
      ${sectionsHtml || '<div class="loading">no categories</div>'}
    `;
  },

  // Build <option>s for the category selector.
  async _categoryOptions(selected) {
    const data = await API.get('/domains');
    const cats = (data && data.categories) || [{ id: 'main', filename: 'main.lst' }];
    return cats.map(c =>
      `<option value="${Toast.escape(c.id)}" ${c.id === selected ? 'selected' : ''}>`
      + `${c.id === 'main' ? 'Main' : c.id.toUpperCase()} (${Toast.escape(c.filename)})</option>`
    ).join('');
  },

  async showAddDialog() {
    const opts = await this._categoryOptions(this.lastCategory);
    showModal('Add Domain', `
      <div class="form-group">
        <label class="form-label">Category</label>
        <select id="addCategory">${opts}</select>
        <div class="card-sub" style="opacity:0.6;font-size:11px;margin-top:4px">
          New IDs (e.g. "github") will create config/domains/&lt;id&gt;.lst.
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">Domain(s) — one per line</label>
        <textarea id="addDomains" rows="3" placeholder="example.com&#10;cdn.example.com"></textarea>
      </div>
      <div class="form-group">
        <label class="form-label">Group inside category (optional comment header)</label>
        <input id="addGroup" placeholder="Service Name">
      </div>
      <div class="btn-group" style="justify-content:flex-end">
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="DomainsPage.add()">Add</button>
      </div>
    `);
  },

  async add() {
    const raw = document.getElementById('addDomains').value.trim();
    const group = document.getElementById('addGroup').value.trim();
    const category = document.getElementById('addCategory').value || 'main';
    if (!raw) return;

    this.lastCategory = category;
    const domains = raw.split('\n').map(s => s.trim()).filter(Boolean);
    closeModal();
    await API.post('/domains', { domains, group: group || null, category });
    App.navigate(location.hash);
  },

  async remove(domain, category) {
    if (!confirmAction(`Remove ${domain} from ${category}?`)) return;
    await API.del('/domains', { domains: [domain], category });
    App.navigate(location.hash);
  },

  async check(domain, btn) {
    const existing = btn.parentElement.querySelector('.inline-result');
    if (existing) existing.remove();

    const data = await API.post('/domains/check', { domain });
    if (!data) return;

    const span = document.createElement('span');
    span.className = `inline-result ${data.in_vpn_ipset ? 'ok' : 'fail'}`;
    // Prefer the first numeric IPv4 (post-CNAME) as the label — old API
    // returned only resolved_ips with mixed CNAMEs+IPs; new API splits them.
    const firstIp = (data.resolved_ips && data.resolved_ips[0])
                 || (data.resolved && data.resolved[0])
                 || 'no IP';
    span.textContent = data.in_vpn_ipset
      ? `${firstIp} in VPN`
      : `${firstIp} NOT in VPN`;
    btn.parentElement.appendChild(span);
  },

  toggleGroup(btn) {
    const body = btn.nextElementSibling;
    if (!body || !body.classList.contains('domain-group-body')) return;

    const expanded = btn.getAttribute('aria-expanded') === 'true';
    btn.setAttribute('aria-expanded', String(!expanded));
    body.hidden = expanded;
  },

  showCheckDialog() {
    showModal('Check Domain', `
      <div class="form-group">
        <label class="form-label">Domain</label>
        <input id="checkDomain" placeholder="us-west-2.console.aws.amazon.com"
               onkeydown="if(event.key==='Enter')DomainsPage.checkFromDialog()">
      </div>
      <div id="checkResult"></div>
      <div class="btn-group" style="justify-content:flex-end;margin-top:12px">
        <button class="btn btn-ghost" onclick="closeModal()">Close</button>
        <button class="btn btn-primary" onclick="DomainsPage.checkFromDialog()">Check</button>
      </div>
    `);
  },

  async checkFromDialog() {
    const domain = document.getElementById('checkDomain').value.trim();
    if (!domain) return;
    const data = await API.post('/domains/check', { domain });
    const el = document.getElementById('checkResult');
    if (!data) { el.innerHTML = '<span class="inline-result fail">Error</span>'; return; }
    const ips = (data.resolved_ips && data.resolved_ips.length)
      ? data.resolved_ips.join(', ')
      : 'none';
    const chain = (data.resolved && data.resolved.length > (data.resolved_ips || []).length)
      ? `<div style="opacity:0.6;font-size:11px;margin-top:4px">CNAME chain: ${Toast.escape(data.resolved.join(' → '))}</div>`
      : '';
    el.innerHTML = `
      <div style="margin-top:12px">
        <div>IPs: <code>${Toast.escape(ips)}</code></div>
        ${chain}
        <div style="margin-top:6px">
          In VPN ipset:
          <span class="inline-result ${data.in_vpn_ipset ? 'ok' : 'fail'}">${data.in_vpn_ipset ? 'Yes' : 'No'}</span>
        </div>
      </div>
    `;
  },

  async showRawEditor(category) {
    category = category || 'main';
    const data = await API.get('/domains');
    if (!data) return;
    const cat = (data.categories || []).find(c => c.id === category);
    if (!cat) return;
    showModal(`Raw editor — ${cat.filename}`, `
      <textarea id="rawDomains" data-category="${Toast.escape(category)}" style="min-height:400px">${Toast.escape(cat.raw)}</textarea>
      <div class="btn-group" style="justify-content:flex-end;margin-top:12px">
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="DomainsPage.saveRaw()">Save</button>
      </div>
    `);
  },

  async showRawCategoryDialog() {
    const opts = await this._categoryOptions(this.lastCategory);
    showModal('Raw editor', `
      <div class="form-group">
        <label class="form-label">Category file</label>
        <select id="rawCategory">${opts}</select>
      </div>
      <div class="btn-group" style="justify-content:flex-end">
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="DomainsPage.openSelectedRawEditor()">Open</button>
      </div>
    `);
  },

  async openSelectedRawEditor() {
    const category = document.getElementById('rawCategory').value || 'main';
    this.lastCategory = category;
    closeModal();
    await this.showRawEditor(category);
  },

  async saveRaw() {
    const ta = document.getElementById('rawDomains');
    const raw = ta.value;
    const category = ta.dataset.category || 'main';
    closeModal();
    await API.put('/domains', { raw, category });
    App.navigate(location.hash);
  },

  mount() {},
  unmount() {},
};
