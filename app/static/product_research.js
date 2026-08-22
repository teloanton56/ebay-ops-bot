(() => {
  'use strict';

  let latestResearch = null;
  let observer = null;

  const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[char]));

  const money = value => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return `$${Number(value).toFixed(2)}`;
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
      const ratio = Number(factor.maximum) > 0
        ? Math.max(0, Math.min(100, Number(factor.earned) / Number(factor.maximum) * 100))
        : 0;
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
        <div><span class="research-kicker">EBAY US · PRODUCT RESEARCH</span><h3>${esc(payload.keyword)}</h3><p>${esc(summary.meaning || '')}</p></div>
        <div class="research-score ${tone}"><strong>${Number(summary.score || 0)}</strong><span>/100</span><small>${esc(summary.verdict || 'À CREUSER')}</small></div>
      </div>
      <div class="research-metrics">
        ${metric('Demande proxy eBay', demand.label || 'À confirmer', demand.evidence || '')}
        ${metric('Concurrence eBay US', competition.label || 'Non mesurée', competition.listings_reference !== null && competition.listings_reference !== undefined ? `${new Intl.NumberFormat('en-US').format(Number(competition.listings_reference))} annonces` : '')}
        ${metric('Prix de référence', price ? money(price.value) : 'Non disponible', 'eBay US · USD')}
        ${metric('Évolution des annonces', trendValue, trend.meaning || '')}
        ${metric('Confiance', summary.confidence || 'Faible', 'Uniquement à partir des données réellement disponibles')}
        ${metric('Volume de recherche exact', 'Non public', 'Aucun chiffre fictif')}
      </div>
      <div class="research-breakdown"><div class="research-breakdown-title"><strong>Pourquoi ce score ?</strong><span>${esc(summary.method || 'EBAY_US_PROXY')}</span></div>${factorRows || '<div class="research-empty">Pas assez de données.</div>'}</div>
      ${missing.length ? `<div class="research-missing"><strong>À confirmer</strong><span>${missing.map(esc).join(' · ')}</span></div>` : ''}
      <div class="research-actions"><button class="btn btn-primary" data-find-suppliers="${esc(payload.keyword)}">Chercher chez CJ</button><button class="btn btn-secondary" type="button" data-action="radar-watch-current">Surveiller</button></div>`;
    area.prepend(card);
  }

  function refreshRadarLabels() {
    const panel = document.querySelector('.radar-scan-panel');
    if (!panel) return;
    const kicker = panel.querySelector('.panel-kicker');
    const title = panel.querySelector('h2');
    const submit = panel.querySelector('button[type="submit"]');
    if (kicker) kicker.textContent = 'PRODUCT RESEARCH · EBAY US';
    if (title) title.textContent = 'Analyser une niche sur eBay US';
    if (submit) submit.textContent = 'Analyser eBay US';
    if (!panel.querySelector('.product-research-intro')) {
      panel.querySelector('.radar-form')?.insertAdjacentHTML(
        'beforebegin',
        '<p class="product-research-intro">Un seul marché : eBay US. Le bot mesure annonces, vendeurs, prix et évolution historique, sans signaux sociaux ni faux volume de recherche.</p>'
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
    } catch {}
    return response;
  };

  function init() {
    refreshRadarLabels();
    watchRadarResults();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
