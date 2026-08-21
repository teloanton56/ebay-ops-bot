(() => {
  'use strict';

  let latestResearch = null;
  let observer = null;

  const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[char]));

  const money = (value, currency = 'EUR') => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    try {
      return new Intl.NumberFormat('fr-FR', {
        style: 'currency', currency, maximumFractionDigits: 2
      }).format(Number(value));
    } catch {
      return `${Number(value).toFixed(2)} ${currency}`;
    }
  };

  function scoreTone(score) {
    if (score >= 75) return 'strong';
    if (score >= 55) return 'good';
    if (score >= 35) return 'caution';
    return 'weak';
  }

  function metric(label, value, help = '') {
    return `<div class="research-metric"><small>${esc(label)}</small><strong>${esc(value)}</strong>${help ? `<span>${esc(help)}</span>` : ''}</div>`;
  }

  function renderResearchSummary() {
    const area = document.querySelector('#radarResults');
    const payload = latestResearch;
    if (!area || !payload?.summary) return;
    if (area.querySelector('[data-product-research-summary]')) return;
    if (area.querySelector('.loading') || area.querySelector('.error-box')) return;
    if (!area.querySelector('.radar-market-results')) return;

    const summary = payload.summary;
    const price = summary.reference_price;
    const trend = summary.trend || {};
    const demand = summary.demand_proxy || {};
    const competition = summary.competition || {};
    const factors = summary.factors || [];
    const missing = summary.missing_signals || [];
    const tone = scoreTone(Number(summary.score || 0));
    const trendValue = trend.change_percent === null || trend.change_percent === undefined
      ? trend.label || 'Premier relevé'
      : `${trend.change_percent >= 0 ? '+' : ''}${Number(trend.change_percent).toFixed(1)} %`;

    const factorRows = factors.map(factor => {
      const ratio = Number(factor.maximum) > 0 ? Math.max(0, Math.min(100, Number(factor.earned) / Number(factor.maximum) * 100)) : 0;
      return `<div class="research-factor">
        <div><span><strong>${esc(factor.label)}</strong><small>${esc(factor.detail)}</small></span><b>${Number(factor.earned).toFixed(0)}/${Number(factor.maximum).toFixed(0)}</b></div>
        <div class="research-factor-bar"><i style="width:${ratio}%"></i></div>
      </div>`;
    }).join('');

    const card = document.createElement('article');
    card.className = `product-research-summary ${tone}`;
    card.dataset.productResearchSummary = 'true';
    card.innerHTML = `
      <div class="research-head">
        <div>
          <span class="research-kicker">PRODUCT RESEARCH · SIGNALS MESURÉS</span>
          <h3>${esc(payload.keyword)}</h3>
          <p>${esc(summary.meaning || '')}</p>
        </div>
        <div class="research-score ${tone}">
          <strong>${Number(summary.score || 0)}</strong><span>/100</span>
          <small>${esc(summary.verdict || 'À CREUSER')}</small>
        </div>
      </div>
      <div class="research-metrics">
        ${metric('Demande estimée', demand.label || 'À confirmer', demand.evidence || '')}
        ${metric('Concurrence eBay', competition.label || 'Non mesurée', competition.listings_reference !== null && competition.listings_reference !== undefined ? `${new Intl.NumberFormat('fr-FR').format(Number(competition.listings_reference))} annonces de référence` : '')}
        ${metric('Prix de référence', price ? money(price.value, price.currency) : 'Non disponible', price?.marketplace || '')}
        ${metric('Évolution de l’offre', trendValue, trend.meaning || '')}
        ${metric('Confiance', summary.confidence || 'Faible', 'Dépend des sources réellement connectées')}
        ${metric('Volume de recherche exact', 'Non public', 'Aucun chiffre fictif n’est généré')}
      </div>
      <div class="research-breakdown">
        <div class="research-breakdown-title"><strong>Pourquoi ce score ?</strong><span>${esc(summary.method || 'MARKET_PROXY_V1')}</span></div>
        ${factorRows || '<div class="research-empty">Pas assez de données pour détailler le score.</div>'}
      </div>
      ${missing.length ? `<div class="research-missing"><strong>À confirmer avant décision</strong><span>${missing.map(esc).join(' · ')}</span></div>` : ''}
      <div class="research-actions">
        <button class="btn btn-primary" data-find-suppliers="${esc(payload.keyword)}">Trouver les fournisseurs</button>
        <button class="btn btn-secondary" type="button" data-action="radar-watch-current">Surveiller ce produit</button>
      </div>`;

    area.prepend(card);
  }

  function refreshRadarLabels() {
    const panel = document.querySelector('.radar-scan-panel');
    if (!panel) return;
    const kicker = panel.querySelector('.panel-kicker');
    const title = panel.querySelector('h2');
    const submit = panel.querySelector('button[type="submit"]');
    if (kicker) kicker.textContent = 'PRODUCT RESEARCH';
    if (title) title.textContent = 'Analyser une opportunité';
    if (submit) submit.textContent = "Analyser l'opportunité";
    if (!panel.querySelector('.product-research-intro')) {
      panel.querySelector('.radar-form')?.insertAdjacentHTML(
        'beforebegin',
        '<p class="product-research-intro">Le bot croise concurrence, présence multi-marchés, prix, rangs Amazon et historique disponibles. Aucun faux volume de recherche n’est inventé.</p>'
      );
    }
  }

  function watchRadarResults() {
    const area = document.querySelector('#radarResults');
    if (!area || observer) return;
    observer = new MutationObserver(() => {
      if (latestResearch) window.setTimeout(renderResearchSummary, 0);
    });
    observer.observe(area, { childList: true, subtree: true });
  }

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async function patchedFetch(input, init = {}) {
    const response = await nativeFetch(input, init);
    try {
      const rawUrl = typeof input === 'string' ? input : input?.url;
      const url = new URL(rawUrl, window.location.origin);
      const method = String(init?.method || input?.method || 'GET').toUpperCase();
      if (url.pathname === '/api/radar/scan' && method === 'POST' && response.ok) {
        response.clone().json().then(data => {
          if (!data?.research_summary) return;
          latestResearch = { keyword: data.keyword || '', summary: data.research_summary };
          window.setTimeout(renderResearchSummary, 80);
          window.setTimeout(renderResearchSummary, 250);
        }).catch(() => {});
      }
    } catch {
      // The original application response must never be blocked by the enhancement layer.
    }
    return response;
  };

  function init() {
    refreshRadarLabels();
    watchRadarResults();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
