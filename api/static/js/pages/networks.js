/* Networks (IP subnets) management page. AppleDouble ._* files are ignored server-side. */

const NetworksPage = {
  async render() {
    const data = await API.get('/networks');
    if (!data) return '<div class="loading">Failed to load</div>';

    const filesHtml = data.files.map(f => `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <div>
            <div class="card-title" style="margin-bottom:2px">${Toast.escape(f.filename)}</div>
            <div style="font-size:13px;font-weight:600">${Toast.escape(f.description || f.name)}</div>
          </div>
          <div class="btn-group">
            <button class="btn btn-ghost btn-sm" onclick="NetworksPage.showAddCidr('${f.name}')">+ CIDR</button>
            <button class="btn btn-danger btn-sm" onclick="NetworksPage.deleteFile('${f.name}')">Delete File</button>
          </div>
        </div>
        <div style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${f.entry_count} entries</div>
        <table>
          <tbody>
            ${f.entries.map(e => `
              <tr>
                <td style="font-family:var(--mono)">${Toast.escape(e)}</td>
                <td style="width:40px;text-align:right">
                  <button class="btn btn-danger btn-sm btn-icon" onclick="NetworksPage.removeCidr('${f.name}','${e}')">&times;</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `).join('');

    return `
      <div class="page-header">
        <h1 class="page-title">IP Networks</h1>
        <button class="btn btn-primary" onclick="NetworksPage.showCreateDialog()">+ New Network File</button>
      </div>
      <div class="card-grid" style="grid-template-columns:1fr">
        ${filesHtml || '<div class="card"><div class="card-sub">No network files</div></div>'}
      </div>
    `;
  },

  showAddCidr(name) {
    showModal(`Add CIDRs to ${name}`, `
      <div class="form-group">
        <label class="form-label">CIDR(s) — one per line</label>
        <textarea id="addCidrs" rows="4" placeholder="192.168.1.0/24&#10;10.0.0.0/8"></textarea>
      </div>
      <div class="btn-group" style="justify-content:flex-end">
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="NetworksPage.addCidr('${name}')">Add</button>
      </div>
    `);
  },

  async addCidr(name) {
    const raw = document.getElementById('addCidrs').value.trim();
    if (!raw) return;
    const cidrs = raw.split('\n').map(s => s.trim()).filter(Boolean);
    closeModal();
    await API.post(`/networks/${name}`, { cidrs });
    App.navigate(location.hash);
  },

  async removeCidr(name, cidr) {
    if (!confirmAction(`Remove ${cidr} from ${name}?`)) return;
    await API.del(`/networks/${name}`, { cidrs: [cidr] });
    App.navigate(location.hash);
  },

  async deleteFile(name) {
    if (!confirmAction(`Delete entire file ${name}-networks.lst?`)) return;
    await API.del(`/networks/${name}/file`);
    App.navigate(location.hash);
  },

  showCreateDialog() {
    showModal('Create Network File', `
      <div class="form-group">
        <label class="form-label">Name (without -networks.lst)</label>
        <input id="netName" placeholder="google">
      </div>
      <div class="form-group">
        <label class="form-label">Description</label>
        <input id="netDesc" placeholder="Google IP ranges">
      </div>
      <div class="form-group">
        <label class="form-label">CIDRs — one per line</label>
        <textarea id="netCidrs" rows="4" placeholder="8.8.8.0/24"></textarea>
      </div>
      <div class="btn-group" style="justify-content:flex-end">
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="NetworksPage.create()">Create</button>
      </div>
    `);
  },

  async create() {
    const name = document.getElementById('netName').value.trim();
    const description = document.getElementById('netDesc').value.trim();
    const raw = document.getElementById('netCidrs').value.trim();
    if (!name || !raw) return;
    const cidrs = raw.split('\n').map(s => s.trim()).filter(Boolean);
    closeModal();
    await API.post('/networks', { name, description, cidrs });
    App.navigate(location.hash);
  },

  mount() {},
  unmount() {},
};
