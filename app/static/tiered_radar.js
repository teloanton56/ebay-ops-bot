(() => {
  'use strict';

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
      const detail = typeof data.detail === 'string'
        ? data.detail
        : data.detail?.message || data.message || `Erreur ${response.status}`;
      throw new Error(detail);
    }
    return data;
  }

  function toast(message) {
    const target = $('#toast');
    if (!target) return;
    target.textContent = message;
    target.classList.add('show');
    clearTimeout(window.__tieredRadarToast);
    window.__tieredRadarToast = setTimeout(() => target.classList.remove('show'), 3500);
  }

  function options(values, current, suffix = '') {
    return values.map(value => `<option value="${value}" ${Number(current) === value ? 'selected' : ''}>${value}${suffix}</option>`).join('');
  }

  function formatNumber(value) {
    return new Intl.NumberFormat('fr-FR').format(Number(value || 0));
  }

  function quotaClass(quota) {
    if (!quota || !quota.limit) return 'neutral';
    const ratio = Number(quota.remaining || 0) / Number(quota.limit || 1);
    return ratio <= 0.25 ? 'danger' : ratio <= 0.45 ? 'review' : 'good';
  }

  function insertControls() {
    const panel = $('#autoRadarPanel');
    if (!panel || $('#tieredRadarControls')) return false;

    const runButton = $('#autoRadarRun');
    if (runButton) runButton.textContent = '✦ Grand scan maintenant';
    const controls = panel.querySelector('.auto-radar-controls');
    if (controls && !$('#quickRadarRun')) {
      const quick = document.createElement('button');
      quick.id = 'quickRadarRun';
      quick.className = 'btn btn-secondary';
      quick.type = 'button';
      quick.textContent = '↻ Scan rapide';
      controls.insertBefore(quick, runButton || controls.firstChild);
      quick.addEventListener('click', runQuick);
    }

    const wrapper = document.createElement('section');
    wrapper.id = 'tieredRadarControls';
    wrapper.className = 'tiered-radar-controls';
    wrapper.innerHTML = `
      <div class="tiered-radar-head">
        <div><span class="panel-kicker">RYTHME & QUOTA</span><h3>Deux niveaux d’analyse</h3><p>Le scan rapide surveille les meilleures pistes. Le grand scan collecte jusqu’à 200 candidats puis approfondit les meilleurs.</p></div>
        <button id="tieredRadarSettingsToggle" class="mini-btn" type="button">Réglages</button>
      </div>
      <div id="tieredRadarKpis" class="tiered-radar-kpis"><div class="loading">Chargement du quota…</div></div>
      <form id="tieredRadarSettingsForm" class="tiered-radar-settings" hidden>
        <label>Scan rapide<select name="quick_minutes"></select></label>
        <label>Grand scan<select name="full_hours"></select></label>
        <label>Candidats collectés<select name="candidate_pool"></select></label>
        <label>Analyses approfondies<select name="deep_candidates"></select></label>
        <label>Confirmations réseaux<select name="social_confirmations"></select></label>
        <label>Pistes surveillées<select name="quick_opportunities"></select></label>
        <label>Réserve de quota<select name="quota_reserve_percent"></select></label>
        <label>Budget Browse/jour<input name="browse_daily_budget" type="number" min="1000" max="100000" step="100" value="5000"></label>
        <div class="tiered-radar-settings-actions"><span id="tieredRadarEstimate"></span><button class="btn btn-primary" type="submit">Enregistrer</button></div>
      </form>`;

    const summary = $('#autoRadarSummary');
    if (summary) summary.insertAdjacentElement('afterend', wrapper);
    else panel.appendChild(wrapper);

    $('#tieredRadarSettingsToggle')?.addEventListener('click', () => {
      const form = $('#tieredRadarSettingsForm');
      if (form) form.hidden = !form.hidden;
    });
    $('#tieredRadarSettingsForm')?.addEventListener('submit', saveSettings);
    return true;
  }

  function fillSettings(settings, estimate) {
    const form = $('#tieredRadarSettingsForm');
    if (!form) return;
    form.elements.quick_minutes.innerHTML = options([15, 30, 60, 120], settings.quick_minutes, ' min');
    form.elements.full_hours.innerHTML = options([1, 2, 4, 6, 12, 24], settings.full_hours, ' h');
    form.elements.candidate_pool.innerHTML = options([50, 100, 150, 200], settings.candidate_pool);
    form.elements.deep_candidates.innerHTML = options([10, 15, 20, 25, 30, 40, 50], settings.deep_candidates);
    form.elements.social_confirmations.innerHTML = options([0, 2, 4, 6, 8, 10], settings.social_confirmations);
    form.elements.quick_opportunities.innerHTML = options([10, 20, 30, 40, 50], settings.quick_opportunities);
    form.elements.quota_reserve_percent.innerHTML = options([10, 15, 20, 25, 30, 40], settings.quota_reserve_percent, ' %');
    form.elements.browse_daily_budget.value = settings.browse_daily_budget;
    const estimateTarget = $('#tieredRadarEstimate');
    if (estimateTarget) {
      estimateTarget.textContent = `≈ ${formatNumber(estimate.estimated_calls_per_day)} appels Browse/jour`;
    }
  }

  function renderKpis(settingsData, quota) {
    const settings = settingsData.settings || {};
    const estimate = settingsData.estimated_daily || {};
    const target = $('#tieredRadarKpis');
    if (!target) return;
    target.innerHTML = `
      <article><small>Scan rapide</small><strong>${esc(settings.quick_minutes || 30)} min</strong><span>${esc(settings.quick_opportunities || 30)} pistes</span></article>
      <article><small>Grand scan</small><strong>${esc(settings.full_hours || 4)} h</strong><span>${esc(settings.candidate_pool || 200)} → ${esc(settings.deep_candidates || 25)}</span></article>
      <article><small>Réseaux</small><strong>${esc(settings.social_confirmations || 0)} max</strong><span>meilleurs nouveaux candidats</span></article>
      <article><small>Prévision</small><strong>${formatNumber(estimate.estimated_calls_per_day)}</strong><span>appels Browse/jour</span></article>
      <article class="quota-card ${quotaClass(quota)}"><small>Quota utilisable</small><strong>${formatNumber(quota?.usable_remaining)}</strong><span>${formatNumber(quota?.remaining)} restants · réserve ${esc(quota?.reserve_percent || settings.quota_reserve_percent || 20)} %</span></article>
      <article><small>Mesure quota</small><strong>${quota?.source === 'EBAY_ANALYTICS' ? 'eBay réel' : 'Budget local'}</strong><span>${quota?.reset ? `reset ${new Date(quota.reset).toLocaleString('fr-FR')}` : 'protection conservatrice'}</span></article>`;
  }

  async function loadControls(forceQuota = false) {
    const [settingsData, quota] = await Promise.all([
      api('/api/radar/auto/settings'),
      api(`/api/radar/auto/quota?force=${forceQuota ? 'true' : 'false'}`),
    ]);
    fillSettings(settingsData.settings || {}, settingsData.estimated_daily || {});
    renderKpis(settingsData, quota);
  }

  async function saveSettings(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = 'Enregistrement…';
    try {
      const payload = Object.fromEntries([...new FormData(form).entries()].map(([key, value]) => [key, Number(value)]));
      const data = await api('/api/radar/auto/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      fillSettings(data.settings || {}, data.estimated_daily || {});
      await loadControls(true);
      form.hidden = true;
      toast('Réglages du Radar appliqués immédiatement');
    } catch (error) {
      toast(`Réglages impossibles : ${error.message}`);
    } finally {
      button.disabled = false;
      button.textContent = 'Enregistrer';
    }
  }

  async function runQuick() {
    const button = $('#quickRadarRun');
    if (!button || button.disabled) return;
    button.disabled = true;
    button.textContent = 'Scan rapide…';
    try {
      const data = await api('/api/radar/auto/run/quick', { method: 'POST' });
      toast(data.status === 'NO_OP'
        ? data.message
        : `${data.opportunities_refreshed || 0} opportunité(s) actualisée(s)`);
      await loadControls(false);
      window.setTimeout(() => location.reload(), 700);
    } catch (error) {
      toast(`Scan rapide impossible : ${error.message}`);
    } finally {
      button.disabled = false;
      button.textContent = '↻ Scan rapide';
    }
  }

  function boot() {
    if (!insertControls()) return false;
    loadControls(false).catch(error => toast(`Quota indisponible : ${error.message}`));
    return true;
  }

  if (!boot()) {
    const observer = new MutationObserver(() => {
      if (boot()) observer.disconnect();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
})();
