(() => {
  'use strict';

  const state = { items: [], status: null, loading: false };
  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[character]));

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const text = await response.text();
    let data = {};
    if (text) {
      try { data = JSON.parse(text); } catch { data = { detail: text }; }
    }
    if (response.status === 401) {
      location.assign('/login');
      throw new Error('Session expirée');
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message || data.message;
      throw new Error(detail || `Erreur ${response.status}`);
    }
    return data;
  }

  function money(value, currency = 'EUR') {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    try {
      return new Intl.NumberFormat('fr-FR', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(value));
    } catch {
      return `${Number(value).toFixed(2)} ${currency}`;
    }
  }

  function dateLabel(value) {
    if (!value) return 'Jamais';
    try { return new Date(value).toLocaleString('fr-FR'); } catch { return String(value); }
  }

  function insertPanel() {
    const section = $('#section-radar');
    if (!section || $('#autoRadarPanel')) return;
    section.querySelector('.auto-discovery-panel')?.classList.add('auto-radar-retired');
    const signalPanel = section.querySelector('.radar-signal-panel');
    if (signalPanel) {
      const kicker = signalPanel.querySelector('.panel-kicker');
      const title = signalPanel.querySelector('h2');
      if (kicker) kicker.textContent = 'VALIDATION SECONDAIRE';
      if (title) title.childNodes[0].textContent = 'Confirmer une opportunité ciblée ';
    }
    const panel = document.createElement('article');
    panel.id = 'autoRadarPanel';
    panel.className = 'panel auto-radar-panel';
    panel.innerHTML = `
      <div class="panel-head">
        <div class="auto-radar-heading">
          <div class="auto-radar-icon">◎</div>
          <div><span class="panel-kicker">DÉCOUVERTE AUTOMATIQUE</span><h2>Le Radar cherche les opportunités à votre place</h2><p>eBay est la source principale. Le bot parcourt les catégories, mesure les candidats, puis utilise YouTube, TikTok et Etsy uniquement comme confirmations ciblées.</p></div>
        </div>
        <div class="auto-radar-controls">
          <button id="autoRadarNotifications" class="btn btn-ghost" type="button">Activer les notifications</button>
          <button id="autoRadarRun" class="btn btn-primary" type="button">✦ Analyser maintenant</button>
        </div>
      </div>
      <div id="autoRadarSummary" class="auto-radar-summary"></div>
      <div class="auto-radar-notice"><span>✓</span><div><strong>Pas de scraping ni de faux volume de recherche.</strong><br>Le score utilise uniquement des signaux officiels disponibles et indique clairement les preuves manquantes.</div></div>
      <div id="autoRadarResults" class="auto-radar-empty"><strong>Chargement des opportunités…</strong><span>Le premier passage automatique peut prendre quelques instants.</span></div>
      <div id="autoRadarFoot" class="auto-radar-secondary"></div>`;
    const firstPanel = section.querySelector('.panel');
    if (firstPanel) firstPanel.insertAdjacentElement('beforebegin', panel);
    else section.appendChild(panel);
    bindPanel();
  }

  function bindPanel() {
    $('#autoRadarRun')?.addEventListener('click', runNow);
    $('#autoRadarNotifications')?.addEventListener('click', requestNotifications);
    document.addEventListener('click', event => {
      const social = event.target.closest('[data-auto-social]');
      if (social) {
        const keyword = social.dataset.autoSocial || '';
        const input = $('#radarSignalQuery');
        if (input) input.value = keyword;
        $('#radarSignalForm')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(() => $('#radarSignalForm')?.requestSubmit(), 300);
        return;
      }
      const dismiss = event.target.closest('[data-auto-dismiss]');
      if (dismiss) dismissOpportunity(Number(dismiss.dataset.autoDismiss));
    });
    refreshNotificationButton();
  }

  function renderSummary() {
    const status = state.status || {};
    const last = status.last_run || {};
    const summary = $('#autoRadarSummary');
    if (!summary) return;
    summary.innerHTML = [
      ['État', status.running ? 'Analyse en cours' : status.ready ? 'Prêt' : 'À configurer'],
      ['Fréquence', status.enabled ? `Toutes les ${status.interval_hours || 6} h` : 'Manuelle'],
      ['Opportunités', status.opportunity_count ?? state.items.length],
      ['Alertes fortes', status.high_score_count ?? state.items.filter(item => Number(item.score) >= 75).length],
      ['Dernier passage', last.finished_at ? dateLabel(last.finished_at) : 'Jamais'],
    ].map(([label, value]) => `<article><small>${esc(label)}</small><strong>${esc(value)}</strong></article>`).join('');
    const foot = $('#autoRadarFoot');
    if (foot) {
      const errors = last.errors?.length ? ` · ${last.errors.length} source(s) partiellement indisponible(s)` : '';
      foot.textContent = `${status.note || ''}${errors}`;
    }
  }

  function card(item) {
    const score = Number(item.score || 0);
    const hot = score >= 75;
    const sources = (item.sources || []).join(' · ') || 'eBay Browse';
    const sold = item.sold_quantity === null || item.sold_quantity === undefined
      ? 'Non fourni'
      : new Intl.NumberFormat('fr-FR').format(Number(item.sold_quantity));
    const velocity = item.sales_velocity === null || item.sales_velocity === undefined
      ? 'Non fournie'
      : `${Number(item.sales_velocity).toFixed(Number(item.sales_velocity) >= 1 ? 1 : 2)}/j`;
    const image = item.image_url
      ? `<img class="auto-opportunity-image" src="${esc(item.image_url)}" alt="">`
      : '<div class="auto-opportunity-image empty">◎</div>';
    const change = item.score_change === null || item.score_change === undefined
      ? ''
      : `<span>${Number(item.score_change) >= 0 ? '+' : ''}${Number(item.score_change).toFixed(0)} pts</span>`;
    return `<article class="auto-opportunity-card ${hot ? 'is-hot' : ''}">
      ${image}
      <div class="auto-opportunity-main">
        <div class="auto-opportunity-top"><h3>${esc(item.keyword)}</h3><div class="auto-opportunity-score ${hot ? 'hot' : ''}"><strong>${score.toFixed(0)}</strong><small>${esc(item.verdict || '')}</small></div></div>
        <div class="auto-opportunity-meta"><span>${esc(item.category_name || 'Catégorie eBay')}</span><span>Confiance ${esc(item.confidence || 'faible')}</span>${change}</div>
        <div class="auto-opportunity-metrics">
          <div><small>Annonces</small><strong>${new Intl.NumberFormat('fr-FR').format(Number(item.total_results || 0))}</strong></div>
          <div><small>Prix médian</small><strong>${money(item.median_price, item.currency || 'EUR')}</strong></div>
          <div><small>Ventes estimées*</small><strong>${sold}</strong></div>
          <div><small>Vitesse observée*</small><strong>${velocity}</strong></div>
          <div><small>Vendeurs</small><strong>${new Intl.NumberFormat('fr-FR').format(Number(item.sellers_sample || 0))}</strong></div>
          <div><small>Signal social</small><strong>${Number(item.social_score || 0).toFixed(0)}/15</strong></div>
        </div>
        <div class="auto-opportunity-sources" title="${esc(sources)}">Sources : ${esc(sources)}</div>
        <div class="auto-opportunity-actions">
          <button class="mini-btn primary" data-find-suppliers="${esc(item.keyword)}">Trouver les fournisseurs</button>
          <button class="mini-btn" data-auto-social="${esc(item.keyword)}">Vérifier réseaux</button>
          ${item.item_url ? `<a class="mini-btn" href="${esc(item.item_url)}" target="_blank" rel="noopener">Voir l’annonce ↗</a>` : ''}
          <button class="mini-btn danger" data-auto-dismiss="${item.id}">Masquer</button>
        </div>
      </div>
    </article>`;
  }

  function renderResults() {
    const area = $('#autoRadarResults');
    if (!area) return;
    if (state.loading) {
      area.className = 'auto-radar-running';
      area.innerHTML = '<span class="spinner"></span> Analyse des catégories et des meilleurs candidats eBay…';
      return;
    }
    if (!state.items.length) {
      area.className = 'auto-radar-empty';
      const ready = state.status?.ready;
      area.innerHTML = ready
        ? '<strong>Aucune opportunité enregistrée pour l’instant.</strong><span>Lancez le premier passage ou attendez le prochain cycle automatique.</span>'
        : '<strong>Le moteur automatique attend les clés eBay Production.</strong><span>Enregistrez les clés dans Connexions puis relancez.</span>';
      return;
    }
    area.className = 'auto-opportunity-grid';
    area.innerHTML = state.items.map(card).join('');
  }

  async function load() {
    try {
      const data = await api('/api/radar/auto/opportunities?limit=30');
      state.items = data.items || [];
      state.status = data.status || {};
      renderSummary();
      renderResults();
      notifyNewOpportunities(state.items);
    } catch (error) {
      const area = $('#autoRadarResults');
      if (area) {
        area.className = 'auto-radar-error';
        area.textContent = `Radar automatique indisponible : ${error.message}`;
      }
    }
  }

  async function runNow() {
    const button = $('#autoRadarRun');
    if (state.loading) return;
    state.loading = true;
    if (button) { button.disabled = true; button.textContent = 'Analyse en cours…'; }
    renderResults();
    try {
      const result = await api('/api/radar/auto/run', { method: 'POST' });
      state.items = result.opportunities || [];
      await load();
    } catch (error) {
      const area = $('#autoRadarResults');
      if (area) {
        area.className = 'auto-radar-error';
        area.textContent = error.message;
      }
    } finally {
      state.loading = false;
      if (button) { button.disabled = false; button.textContent = '✦ Analyser maintenant'; }
      renderResults();
    }
  }

  async function dismissOpportunity(id) {
    if (!id) return;
    try {
      await api(`/api/radar/auto/opportunities/${id}/dismiss`, { method: 'POST' });
      state.items = state.items.filter(item => Number(item.id) !== id);
      renderSummary();
      renderResults();
    } catch (error) {
      const area = $('#autoRadarResults');
      if (area) area.insertAdjacentHTML('afterbegin', `<div class="auto-radar-error">${esc(error.message)}</div>`);
    }
  }

  function refreshNotificationButton() {
    const button = $('#autoRadarNotifications');
    if (!button) return;
    if (!('Notification' in window)) {
      button.hidden = true;
      return;
    }
    if (Notification.permission === 'granted') button.textContent = 'Notifications activées ✓';
    else if (Notification.permission === 'denied') button.textContent = 'Notifications bloquées par Safari';
    else button.textContent = 'Activer les notifications';
  }

  async function requestNotifications() {
    if (!('Notification' in window)) return;
    try { await Notification.requestPermission(); } catch {}
    refreshNotificationButton();
  }

  async function showNotification(item) {
    const title = `Opportunité eBay · ${Number(item.score || 0).toFixed(0)}/100`;
    const options = {
      body: `${item.keyword} — ${item.verdict || 'À analyser'}`,
      icon: '/static/app-icon.svg',
      badge: '/static/app-icon.svg',
      tag: `radar-${item.id}`,
      data: { url: '/#radar' },
    };
    try {
      const registration = await navigator.serviceWorker?.ready;
      if (registration?.showNotification) await registration.showNotification(title, options);
      else new Notification(title, options);
    } catch {}
  }

  function notifyNewOpportunities(items) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const storageKey = 'opsbot-auto-radar-notified-v1';
    let known = [];
    try { known = JSON.parse(localStorage.getItem(storageKey) || '[]'); } catch {}
    const knownSet = new Set((known || []).map(String));
    const fresh = items.filter(item => Number(item.score || 0) >= 75 && !knownSet.has(String(item.id))).slice(0, 3);
    fresh.forEach(item => showNotification(item));
    const next = [...new Set([...items.filter(item => Number(item.score || 0) >= 75).map(item => String(item.id)), ...knownSet])].slice(0, 100);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch {}
  }

  function init() {
    insertPanel();
    load();
    window.setInterval(() => {
      if (!document.hidden) load();
    }, 5 * 60 * 1000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
