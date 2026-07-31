/* API client for VPN Gateway */

const API = {
  base: '/api/v1',

  async request(method, path, body) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    try {
      const res = await fetch(this.base + path, opts);
      const text = await res.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (e) {
        const detail = text ? text.slice(0, 160) : (res.statusText || 'empty response');
        Toast.show(`Connection error: HTTP ${res.status} ${detail}`, 'error');
        return null;
      }

      if (data.log) {
        Toast.show(data.log, 'success');
      }
      if (!res.ok && data.status !== 'error') {
        Toast.show(data.error || `HTTP ${res.status}`, 'error');
        return null;
      }
      if (data.status === 'error') {
        Toast.show(data.error || 'Unknown error', 'error');
        return null;
      }
      return data.data;
    } catch (e) {
      Toast.show('Connection error: ' + e.message, 'error');
      return null;
    }
  },

  get(path) { return this.request('GET', path); },
  post(path, body) { return this.request('POST', path, body); },
  put(path, body) { return this.request('PUT', path, body); },
  del(path, body) { return this.request('DELETE', path, body); },
};

/* Toast notification system */
const Toast = {
  show(message, type = 'success', duration = 5000) {
    const container = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    // Truncate long log messages
    const short = message.length > 200 ? message.slice(0, 200) + '...' : message;
    el.innerHTML = `<span>${this.escape(short)}</span><span class="toast-close" onclick="this.parentElement.remove()">&times;</span>`;
    container.appendChild(el);
    setTimeout(() => el.remove(), duration);
  },

  escape(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }
};

/* Modal system */
function showModal(title, html) {
  document.getElementById('modal').innerHTML = `<div class="modal-title">${title}</div>${html}`;
  document.getElementById('modal').classList.add('show');
  document.getElementById('modalBackdrop').classList.add('show');
}

function closeModal() {
  document.getElementById('modal').classList.remove('show');
  document.getElementById('modalBackdrop').classList.remove('show');
}
window.closeModal = closeModal;

/* Helper: format bytes */
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
  return (bytes / 1073741824).toFixed(1) + ' GB';
}

/* Helper: confirm action */
function confirmAction(message) {
  return window.confirm(message);
}
