/* SPA Router and App initialization */

const App = {
  pages: {
    '/': DashboardPage,
    '/domains': DomainsPage,
    '/networks': NetworksPage,
    '/routing': RoutingPage,
    '/services': ServicesPage,
    '/dns': DnsPage,
    '/notifications': NotificationsPage,
  },

  currentPage: null,
  embeddedDashboard: false,

  async navigate(hash) {
    const path = this.embeddedDashboard
      ? '/'
      : ((hash || '#/').replace('#', '') || '/');
    const page = this.pages[path];
    if (!page) return;

    // Unmount previous page
    if (this.currentPage && this.currentPage.unmount) {
      this.currentPage.unmount();
    }

    // Update nav
    document.querySelectorAll('.nav-item').forEach(el => {
      const href = el.getAttribute('href').replace('#', '');
      el.classList.toggle('active', href === path);
    });

    // Render
    const content = document.getElementById('content');
    content.innerHTML = '<div class="loading">Loading...</div>';

    const html = await page.render();
    content.innerHTML = html;

    this.currentPage = page;
    if (page.mount) page.mount();
  },

  async loadVersion() {
    try {
      const resp = await fetch('/api/v1/health');
      const data = await resp.json();
      const el = document.getElementById('sidebarVersion');
      if (el) {
        const ver = data.version || '?';
        const date = data.version_date ? ` · ${data.version_date}` : '';
        el.textContent = `v${ver}${date}`;
      }
    } catch (_) {}
  },

  init() {
    this.embeddedDashboard = location.pathname.replace(/\/+$/, '') === '/dash-view';
    window.VPNGW_DASH_VIEW = this.embeddedDashboard;
    document.body.classList.toggle('dash-view', this.embeddedDashboard);
    window.addEventListener('hashchange', () => this.navigate(location.hash));
    this.navigate(location.hash || '#/');
    this.loadVersion();
  }
};

App.init();
