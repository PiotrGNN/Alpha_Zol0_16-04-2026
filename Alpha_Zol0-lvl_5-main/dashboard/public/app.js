const API_URL = window.ZOLO_API_URL || 'http://localhost:8000';
const app = document.querySelector('#app');

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
  const token = localStorage.getItem('zol0_token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

async function checkout(productCode) {
  try {
    const result = await api('/billing/checkout', {
      method: 'POST',
      body: JSON.stringify({ product_code: productCode }),
    });
    window.location.assign(result.checkout_url);
  } catch (error) {
    alert(`Checkout niedostępny: ${error.message}`);
  }
}

function pricing() {
  app.innerHTML = `<h1>Research zamiast obietnic</h1>
    <p>Dashboard analiz, sygnałów i raportów backtestowych. Publiczny live trading nie jest częścią produktu.</p>
    <section class="plans">
      <article><h2>Starter</h2><strong>29 zł / mies.</strong><p>Podstawowe raporty i insighty.</p><button data-buy="starter">Wybierz Starter</button></article>
      <article><h2>Pro</h2><strong>79 zł / mies.</strong><p>Alerty, historia decyzji i eksport.</p><button data-buy="pro">Wybierz Pro</button></article>
      <article><h2>Raport</h2><strong>Zakup jednorazowy</strong><p>Pojedynczy raport bez abonamentu.</p><button data-buy="report">Kup raport</button></article>
    </section>`;
  app.querySelectorAll('[data-buy]').forEach(button => button.addEventListener('click', () => checkout(button.dataset.buy)));
}

function onboarding() {
  app.innerHTML = `<h1>Onboarding</h1><form id="onboarding-form">
    <label>Rynek<select name="market"><option>KuCoin futures</option></select></label>
    <label>Cel<select name="goal"><option>Research</option><option>Sygnały</option><option>Backtest</option></select></label>
    <button>Zapisz profil</button></form><p id="result"></p>`;
  document.querySelector('#onboarding-form').addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api('/events', { method: 'POST', body: JSON.stringify({ event_name: 'onboarding_completed', properties: data }) });
      document.querySelector('#result').textContent = 'Profil zapisany.';
    } catch (error) {
      document.querySelector('#result').textContent = error.message;
    }
  });
}

async function billing() {
  app.innerHTML = '<h1>Konto i billing</h1><p>Ładowanie…</p>';
  try {
    const me = await api('/auth/me');
    app.innerHTML = `<h1>Konto i billing</h1><p>${me.email}</p><p>Plan: ${me.active_plan || 'brak aktywnego planu'}</p><button id="portal">Zarządzaj subskrypcją</button>`;
    document.querySelector('#portal').addEventListener('click', async () => {
      const result = await api('/billing/portal', { method: 'POST' });
      window.location.assign(result.portal_url);
    });
  } catch (error) {
    app.innerHTML = `<h1>Konto i billing</h1><p>${error.message}</p>`;
  }
}

async function admin() {
  app.innerHTML = '<h1>Admin KPI</h1><p>Ładowanie…</p>';
  try {
    const [funnel, mrr, health] = await Promise.all([
      api('/internal/funnel'), api('/internal/mrr'), api('/internal/runtime-health'),
    ]);
    app.innerHTML = `<h1>Admin KPI</h1><section class="metrics"><pre>${JSON.stringify({ funnel, mrr, health }, null, 2)}</pre></section>`;
  } catch (error) {
    app.innerHTML = `<h1>Admin KPI</h1><p>${error.message}</p>`;
  }
}

const routes = { '/': pricing, '/pricing': pricing, '/onboarding': onboarding, '/account/billing': billing, '/admin': admin };
function render() { (routes[window.location.pathname] || pricing)(); }
document.addEventListener('click', event => {
  const link = event.target.closest('[data-route]');
  if (!link) return;
  event.preventDefault();
  history.pushState({}, '', link.getAttribute('href'));
  render();
});
window.addEventListener('popstate', render);
render();
