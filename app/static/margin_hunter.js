(() => {
  'use strict';

  const candidateStore = new Map();
  let candidateCounter = 0;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

  function money(value, currency = 'EUR') {
    if (value === null || value === undefined || value === '') return 'À confirmer';
    const amount = Number(value);
    if (!Number.isFinite(amount)) return 'À confirmer';
    return `${amount.toFixed(2)} ${currency}`;
  }

  function percent(value) {
    if (value === null || value === undefined || value === '') return 'À confirmer';
    const amount = Number(value);
    return Number.isFinite(amount) ? `${amount.toFixed(1)} %` : 'À confirmer';
  }

  function rememberCandidate(candidate) {
    const id = `margin-${++candidateCounter}`;
    candidateStore.set(id, candidate);
    return id;
  }

  function ensurePanel() {
    const section = document.querySelector('#section-radar');
    if (!section || section.querySelector('.margin-hunter-panel')) return;
    const head = section.querySelector('.section-head');
    if (!head) return;

    const panel = document.createElement('article');
    panel.className = 'panel margin-hunter-panel';
    panel.innerHTML = `
      <div class="panel-head">
        <div>
          <span class="panel-kicker">MARGIN HUNTER</span>
          <h2>Chasser les produits à forte marge</h2>
          <p>Compare le prix eBay France aux coûts CJ / AliExpress. Objectif : coût livré ≤ 30 % du prix eBay.</p>
        </div>
        <span class="status-badge good">Top 10</span>
      </div>
      <form id="marginHunterForm" class="radar-form">
        <label class="full">Produit ou niche
          <input id="marginHunterQuery" list="marginHunterSeeds" required placeholder="Ex. car organizer, replacement knob, card binder…">
          <datalist id="marginHunterSeeds">
            <option value="car organizer"></option>
            <option value="replacement knob"></option>
            <option value="trading card binder"></option>
            <option value="drawer organizer"></option>
            <option value="pet travel bowl"></option>
          </datalist>
        </label>
        <div class="full radar-actions"><button class="btn btn-primary" type="submit">Chercher les meilleures marges</button></div>
      </form>
      <div id="marginHunterResults" class="empty-state compact">
        <strong>Aucune chasse lancée</strong>
        <span>Le bot mesure eBay puis classe les offres fournisseurs les plus intéressantes.</span>
      </div>`;
    head.insertAdjacentElement('afterend', panel);
  }

  function marketSummary(data) {
    const market = data.market || {};
    const demand = market.demand_proxy || {};
    const demandText = market.amazon_signal_used
      ? `${demand.label || 'À confirmer'}${demand.score != null ? ` · ${Math.round(Number(demand.score))}/100` : ''}`
      : 'À confirmer (Amazon non utilisé)';
    return `
      <div class="info-box">
        <strong>Référence eBay : ${esc(money(market.reference_price, market.currency || 'EUR'))}</strong>
        <p>${esc(market.active_listings ?? 0)} annonce(s) actives · concurrence ${esc(market.competition || 'non mesurée')} · demande proxy ${esc(demandText)} · objectif coût livré ≤ ${esc(data.target_landed_ratio_percent || 30)} %.</p>
      </div>`;
  }

  function candidateCard(candidate, rank) {
    const id = rememberCandidate(candidate);
    const verified = Boolean(candidate.verified);
    const confidenceClass = verified ? 'good' : 'neutral';
    const image = candidate.image_url
      ? `<img src="${esc(candidate.image_url)}" alt="" loading="lazy">`
      : '<div class="image-placeholder">API</div>';
    const shipping = verified
      ? `${money(candidate.shipping_cost)} · ${candidate.shipping_days ?? '—'} j`
      : `À confirmer · budget max ${money(candidate.shipping_budget_to_30)}`;
    const margin = verified
      ? percent(candidate.margin_percent)
      : `plafond ${percent(candidate.margin_ceiling_percent)}`;
    const landed = verified ? money(candidate.landed_cost) : 'À confirmer';
    const goal = candidate.goal_hit ? '<span class="status-badge good">Objectif ≤30% atteint</span>' : '';
    const addLabel = verified ? 'Ajouter aux Produits' : 'Ajouter à valider';
    const sourceLink = candidate.source_url
      ? `<a class="mini-btn" href="${esc(candidate.source_url)}" target="_blank" rel="noopener">Voir le produit ↗</a>`
      : '';
    return `
      <article class="cj-card margin-hunter-card">
        ${image}
        <div class="cj-card-body">
          <div class="radar-market-head"><strong>#${rank} · ${esc(candidate.provider)}</strong><span class="status-badge ${confidenceClass}">${esc(candidate.confidence || '')}</span></div>
          <h3>${esc(candidate.name || 'Produit')}</h3>
          <div class="cj-price">Score ${esc(candidate.score ?? 0)}/100 · ${esc(candidate.verdict || '')}</div>
          <div class="cj-card-meta">
            <span>Produit ${esc(money(candidate.supplier_cost))}</span>
            <span>Livraison ${esc(shipping)}</span>
            <span>Coût livré ${esc(landed)}</span>
            <span>eBay ${esc(money(candidate.reference_price))}</span>
            <span>Ratio ${esc(percent(candidate.cost_ratio_percent))}</span>
            <span>Marge ${esc(margin)}</span>
            <span>Pertinence ${esc(Math.round(Number(candidate.match_strength || 0) * 100))}%</span>
          </div>
          <div class="panel-actions">${goal}<button class="mini-btn primary" data-margin-add="${id}">${addLabel}</button>${sourceLink}</div>
        </div>
      </article>`;
  }

  function renderResults(area, data) {
    candidateStore.clear();
    candidateCounter = 0;
    const candidates = data.candidates || [];
    if (!candidates.length) {
      const error = (data.errors || []).find(item => !String(item.message || '').includes('hors sujet'));
      area.className = 'empty-state compact';
      area.innerHTML = `<strong>Aucun candidat rentable trouvé</strong><span>${esc(error?.message || 'Essayez un produit plus précis ou une autre niche.')}</span>`;
      return;
    }
    const verified = candidates.filter(item => item.verified).length;
    const goalHits = candidates.filter(item => item.goal_hit).length;
    area.className = 'margin-hunter-results';
    area.innerHTML = `${marketSummary(data)}
      <div class="info-box"><strong>${candidates.length} candidat(s) classé(s)</strong><p>${verified} marge(s) vérifiée(s) avec transport · ${goalHits} candidat(s) sous l’objectif 30 %. AliExpress reste préliminaire si le transport manque.</p></div>
      <div class="radar-supplier-grid">${candidates.map((candidate, index) => candidateCard(candidate, index + 1)).join('')}</div>
      <small class="seller">${esc(data.note || '')}</small>`;
  }

  async function runHunter(form) {
    const input = form.querySelector('#marginHunterQuery');
    const area = document.querySelector('#marginHunterResults');
    const query = input?.value.trim();
    if (!query || !area) return;
    const button = form.querySelector('button[type="submit"]');
    const previous = button?.textContent;
    if (button) { button.disabled = true; button.textContent = 'Analyse eBay + fournisseurs…'; }
    area.className = 'loading';
    area.textContent = 'Mesure du marché eBay, calcul des coûts CJ et classement des marges…';
    try {
      const response = await fetch('/api/radar/margin-hunter', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({keyword: query, limit: 10}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
      renderResults(area, data);
    } catch (error) {
      area.className = 'error-box';
      area.textContent = error.message;
    } finally {
      if (button) { button.disabled = false; button.textContent = previous || 'Chercher les meilleures marges'; }
    }
  }

  async function addCandidate(id, button) {
    const candidate = candidateStore.get(id);
    if (!candidate?.add_payload || !button) return;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = candidate.verified ? 'Recalcul & ajout…' : 'Ajout…';
    try {
      const response = await fetch('/api/supplier-flow/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(candidate.add_payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
      button.textContent = 'Ajouté ✓';
      button.classList.remove('primary');
      button.title = data.message || 'Produit ajouté';
      if (!data.pricing_ready) alert(data.message || 'Produit ajouté, mais la livraison reste à confirmer.');
    } catch (error) {
      button.disabled = false;
      button.textContent = previous;
      alert(`Ajout impossible : ${error.message}`);
    }
  }

  document.addEventListener('submit', event => {
    const form = event.target.closest('#marginHunterForm');
    if (!form) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    runHunter(form);
  }, true);

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-margin-add]');
    if (!button) return;
    event.preventDefault();
    addCandidate(button.dataset.marginAdd, button);
  });

  const run = () => ensurePanel();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once: true});
  else run();
  setTimeout(run, 500);
  setTimeout(run, 1500);
})();
