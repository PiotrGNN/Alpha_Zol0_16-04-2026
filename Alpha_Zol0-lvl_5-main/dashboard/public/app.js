const API_URL = window.ZOLO_API_URL || 'http://localhost:8000';
const app = document.querySelector('#app');
const notice = document.querySelector('#notice');
const authLink = document.querySelector('#auth-link');
const logoutButton = document.querySelector('#logout');

function token() {
  const expiresAt = Number(localStorage.getItem('zol0_token_expires_at') || 0);
  if (expiresAt && Date.now() >= expiresAt) clearSession();
  return localStorage.getItem('zol0_token');
}

function setSession(payload) {
  localStorage.setItem('zol0_token', payload.access_token);
  localStorage.setItem('zol0_token_expires_at', String(Date.now() + Number(payload.expires_in || 0) * 1000));
  refreshAuthControls();
}

function clearSession() {
  localStorage.removeItem('zol0_token');
  localStorage.removeItem('zol0_token_expires_at');
  refreshAuthControls();
}

function refreshAuthControls() {
  const authenticated = Boolean(localStorage.getItem('zol0_token'));
  authLink.textContent = authenticated ? 'Konto' : 'Logowanie';
  authLink.setAttribute('href', authenticated ? '/account/billing' : '/login');
  logoutButton.hidden = !authenticated;
}

function showNotice(message, kind = 'info') {
  notice.textContent = message || '';
  notice.dataset.kind = kind;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
  const currentToken = token();
  if (currentToken) headers.set('Authorization', `Bearer ${currentToken}`);
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const contentType = response.headers.get('content-type') || '';
  const body = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text();
  if (!response.ok) {
    if (response.status === 401) clearSession();
    throw new Error(body.detail || body || `HTTP ${response.status}`);
  }
  return body;
}

async function checkout(productCode, artifactSlug = null) {
  try {
    const result = await api('/billing/checkout', {
      method: 'POST',
      body: JSON.stringify({ product_code: productCode, artifact_slug: artifactSlug }),
    });
    window.location.assign(result.checkout_url);
  } catch (error) {
    showNotice(`Checkout niedostępny: ${error.message}`, 'error');
  }
}

function pricing() {
  app.innerHTML = `<h1>Research zamiast obietnic</h1>
    <p>KuCoin PAPER research, sygnały i raporty backtestowe. Publiczny LIVE trading nie jest częścią produktu.</p>
    <section class="plans">
      <article><h2>Starter</h2><strong>29 zł / mies.</strong><p>Raporty i historia sygnałów.</p><button data-buy="starter">Wybierz Starter</button></article>
      <article><h2>Pro</h2><strong>79 zł / mies.</strong><p>Backtesty, alerty i eksport.</p><button data-buy="pro">Wybierz Pro</button></article>
      <article><h2>Raport</h2><strong>Zakup jednorazowy</strong><p>Dostęp wyłącznie do zakupionego artefaktu.</p><button data-buy="report" data-artifact="single-research-report">Kup raport</button></article>
    </section>`;
  app.querySelectorAll('[data-buy]').forEach(button => button.addEventListener('click', () => checkout(button.dataset.buy, button.dataset.artifact || null)));
}

function authForm(mode = 'login') {
  const register = mode === 'register';
  app.innerHTML = `<h1>${register ? 'Rejestracja' : 'Logowanie'}</h1>
    <form id="auth-form">
      <label>E-mail<input name="email" type="email" autocomplete="email" required></label>
      <label>Hasło<input name="password" type="password" minlength="10" autocomplete="${register ? 'new-password' : 'current-password'}" required></label>
      <button>${register ? 'Utwórz konto' : 'Zaloguj'}</button>
    </form>
    <p><a href="${register ? '/login' : '/register'}" data-route>${register ? 'Mam konto' : 'Załóż konto'}</a></p>
    <p><a href="/forgot-password" data-route>Nie pamiętam hasła</a></p>`;
  document.querySelector('#auth-form').addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const result = await api(`/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify(data) });
      setSession(result);
      history.pushState({}, '', '/research');
      showNotice('Sesja została utworzona.', 'success');
      render();
    } catch (error) {
      showNotice(error.message, 'error');
    }
  });
}

function forgotPassword() {
  app.innerHTML = `<h1>Reset hasła</h1><form id="forgot-form">
    <label>E-mail<input name="email" type="email" required></label><button>Wyślij link</button></form>`;
  document.querySelector('#forgot-form').addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api('/auth/password-reset/request', { method: 'POST', body: JSON.stringify(data) });
      showNotice('Jeżeli konto istnieje, link resetujący został wysłany.', 'success');
    } catch (error) {
      showNotice(error.message, 'error');
    }
  });
}

function resetPassword() {
  const resetToken = new URLSearchParams(location.search).get('token') || '';
  app.innerHTML = `<h1>Ustaw nowe hasło</h1><form id="reset-form">
    <label>Nowe hasło<input name="new_password" type="password" minlength="10" required></label><button>Zmień hasło</button></form>`;
  document.querySelector('#reset-form').addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api('/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify({ token: resetToken, ...data }) });
      clearSession();
      history.pushState({}, '', '/login');
      showNotice('Hasło zmienione. Zaloguj się ponownie.', 'success');
      render();
    } catch (error) {
      showNotice(error.message, 'error');
    }
  });
}

async function research() {
  app.innerHTML = '<h1>Research</h1><p>Ładowanie…</p>';
  try {
    const catalog = await api('/resources/catalog');
    app.innerHTML = `<h1>Research</h1><div class="toolbar"><a href="/alerts" data-route>Alerty Pro</a><button id="export-artifacts">Eksport Pro</button></div>
      <section class="resource-grid">${catalog.map(item => `<article><small>${item.resource_type} · ${item.required_plan}</small><h2>${item.title}</h2><p>${item.summary}</p>${item.accessible ? `<button data-open="${item.slug}">Otwórz</button>` : item.required_plan === 'one_time' ? `<button data-purchase="${item.slug}">Kup ten raport</button>` : '<span class="locked">Brak entitlementu</span>'}</article>`).join('')}</section>`;
    app.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => openArtifact(button.dataset.open)));
    app.querySelectorAll('[data-purchase]').forEach(button => button.addEventListener('click', () => checkout('report', button.dataset.purchase)));
    document.querySelector('#export-artifacts').addEventListener('click', () => downloadExport('artifacts'));
  } catch (error) {
    app.innerHTML = `<h1>Research</h1><p>${error.message}</p><p><a href="/login" data-route>Zaloguj się</a></p>`;
  }
}

async function openArtifact(slug) {
  try {
    const artifact = await api(`/resources/artifacts/${encodeURIComponent(slug)}`);
    app.innerHTML = `<p><a href="/research" data-route>← Research</a></p><h1>${artifact.title}</h1><p>${artifact.summary}</p><pre>${JSON.stringify(artifact.content, null, 2)}</pre>`;
    history.pushState({}, '', `/research/${slug}`);
  } catch (error) {
    showNotice(error.message, 'error');
  }
}

async function downloadExport(type) {
  try {
    const headers = token() ? { Authorization: `Bearer ${token()}` } : {};
    const response = await fetch(`${API_URL}/resources/export/${type}`, { headers });
    if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `zol0-${type}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    showNotice(error.message, 'error');
  }
}

async function alerts() {
  app.innerHTML = `<h1>Alerty Pro</h1><form id="alert-form">
    <label>Nazwa<input name="name" required></label><label>Symbol<input name="symbol" value="BTCUSDTM" required></label>
    <label>Próg ruchu %<input name="move_pct" type="number" step="0.1" value="1"></label><button>Dodaj alert</button></form><section id="alert-list"></section>`;
  const load = async () => {
    const rows = await api('/resources/alerts');
    document.querySelector('#alert-list').innerHTML = rows.map(row => `<article><strong>${row.name}</strong><p>${row.symbol}</p><pre>${JSON.stringify(row.condition)}</pre></article>`).join('') || '<p>Brak alertów.</p>';
  };
  try { await load(); } catch (error) { showNotice(error.message, 'error'); }
  document.querySelector('#alert-form').addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api('/resources/alerts', { method: 'POST', body: JSON.stringify({ name: data.name, symbol: data.symbol, condition: { move_pct: Number(data.move_pct) } }) });
      showNotice('Alert utworzony.', 'success');
      await load();
    } catch (error) { showNotice(error.message, 'error'); }
  });
}

function onboarding() {
  app.innerHTML = `<h1>Onboarding</h1><form id="onboarding-form">
    <label>Rynek<select name="market"><option>KuCoin futures</option></select></label>
    <label>Cel<select name="goal"><option>Research</option><option>Sygnały</option><option>Backtest</option></select></label>
    <button>Zapisz profil</button></form>`;
  document.querySelector('#onboarding-form').addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api('/events', { method: 'POST', body: JSON.stringify({ event_name: 'onboarding_completed', properties: data }) });
      showNotice('Profil zapisany.', 'success');
    } catch (error) { showNotice(error.message, 'error'); }
  });
}

async function billing() {
  app.innerHTML = '<h1>Konto i billing</h1><p>Ładowanie…</p>';
  const checkoutState = new URLSearchParams(location.search).get('checkout');
  if (checkoutState === 'success') showNotice('Płatność przyjęta. Dostęp pojawi się po potwierdzeniu webhooka.', 'success');
  if (checkoutState === 'cancelled') showNotice('Checkout anulowany.', 'info');
  try {
    const me = await api('/auth/me');
    app.innerHTML = `<h1>Konto i billing</h1><p>${me.email}</p><p>Plan: ${me.active_plan || 'brak aktywnego planu'}</p><button id="portal">Zarządzaj subskrypcją</button>`;
    document.querySelector('#portal').addEventListener('click', async () => {
      try {
        const result = await api('/billing/portal', { method: 'POST' });
        window.location.assign(result.portal_url);
      } catch (error) { showNotice(error.message, 'error'); }
    });
  } catch (error) {
    app.innerHTML = `<h1>Konto i billing</h1><p>${error.message}</p><p><a href="/login" data-route>Zaloguj się</a></p>`;
  }
}

async function admin() {
  app.innerHTML = '<h1>Admin KPI</h1><p>Ładowanie…</p>';
  try {
    const [funnel, mrr, health] = await Promise.all([api('/internal/funnel'), api('/internal/mrr'), api('/internal/runtime-health')]);
    app.innerHTML = `<h1>Admin KPI</h1><section class="metrics"><pre>${JSON.stringify({ funnel, mrr, health }, null, 2)}</pre></section>`;
  } catch (error) { app.innerHTML = `<h1>Admin KPI</h1><p>${error.message}</p>`; }
}

logoutButton.addEventListener('click', async () => {
  try { await api('/auth/logout', { method: 'POST' }); } catch (_) { /* local logout remains safe */ }
  clearSession();
  history.pushState({}, '', '/login');
  showNotice('Wylogowano.', 'success');
  render();
});

const routes = {
  '/': pricing,
  '/pricing': pricing,
  '/login': () => authForm('login'),
  '/register': () => authForm('register'),
  '/forgot-password': forgotPassword,
  '/reset-password': resetPassword,
  '/research': research,
  '/alerts': alerts,
  '/onboarding': onboarding,
  '/account/billing': billing,
  '/admin': admin,
};

function render() {
  refreshAuthControls();
  showNotice('');
  if (window.location.pathname.startsWith('/research/')) {
    openArtifact(window.location.pathname.split('/').pop());
    return;
  }
  (routes[window.location.pathname] || pricing)();
}

document.addEventListener('click', event => {
  const link = event.target.closest('[data-route]');
  if (!link) return;
  event.preventDefault();
  history.pushState({}, '', link.getAttribute('href'));
  render();
});
window.addEventListener('popstate', render);
render();
