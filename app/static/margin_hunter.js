(() => {
  'use strict';

  const candidateStore = new Map();
  let candidateCounter = 0;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

  function money(value) {
    if (value === null || value === undefined || value === '') return '—';
    const amount = Number(value);
    return Number.isFinite(amount) ? `$${amount.toFixed(2)}` : '—';
  }

  function percent(value) {
    const amount = Number(value);
    return Number.isFinite(amount) ? `${amount.toFixed(1)} %` : '—';
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
          <span class="panel-kicker">MARGIN HUNTER · US</span>
          <h2>Trouver les produits CJ rentables sur eBay US</h2>
          <p>Prix eBay.com réel → coût CJ livré aux États-Unis → marge nette estimée. Stock US prioritaire, Chine seulement si les seuils renforcés passent.</p>
        </div>
        <span class="status-badge good">CJ ONLY</span>
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
        <div class="full radar-actions"><button class="btn btn-primary" type="submit">Chercher les meilleures marges US</button></div>
      </form>
      <div id="marginHunterResults" class="empty-state compact">
        <strong>Aucune recherche lancée</strong>
        <span>Le bot compare eBay US à CJ en USD.</span>
      </div>`;
    head.insertAdjacentElement('afterend', panel);
  }

  function marketSummary(data) {
    const market = data.market || {};
    const demand = market.demand_proxy || {};
    const demandText = demand.score != null
      ? `${demand.label || 'Signal eBay'} · ${Math.round(Number(demand.score))}/100`
      : 'non mesurée';
    return `
      <div class="info-box">
        <strong>eBay US : ${esc(money(market.reference_price))} médian</strong>
        <p>${esc(market.active_listings ?? 0)} annonce(s) actives · concurrence ${esc(market.competition || 'non mesurée')} · demande proxy ${esc(demandText)}.</p>
      </div>`;
  }

  function candidateCard(candidate, rank) {
    const id = rememberCandidate(candidate);
    const image = candidate.image_url
      ? `<img src="${esc(candidate.image_url)}" alt="" loading="lazy">`
      : '<div class="image-placeholder">CJ</div>';
    const route = candidate.route || (candidate.warehouse === 'US' ? 'CJ US' : 'CJ China → US');
    const requirements = candidate.requirements || {};
    const goal = candidate.goal_hit
      ? '<span class="status-badge good">Marge + coût cible OK</span>'
      : candidate.route_eligible
        ? '<span class="status-badge neutral">Route exploitable</span>'
        : '<span class="status-badge danger">Hors seuils</span>';
    const add = candidate.route_eligible
      ? `<button class="mini-btn primary" data-margin-add="${id}">Ajouter aux Produits</button>`
      : '<span class="candidate-pending">Ne pas lancer</span>';
    return `
      <article class="cj-card margin-hunter-card">
        ${image}
        <div class="cj-card-body">
          <div class="radar-market-head"><strong>#${rank} · ${esc(route)}</strong><span class="status-badge ${candidate.warehouse === 'US' ? 'good' : 'neutral'}">${esc(candidate.verdict || '')}</span></div>
          <h3>${esc(candidate.name || 'CJ product')}</h3>
          <div class="cj-price">Score ${esc(candidate.score ?? 0)}/100</div>
          <div class="cj-card-meta">
            <span>Produit ${esc(money(candidate.supplier_cost))}</span>
            <span>Transport ${esc(money(candidate.shipping_cost))} · ${esc(candidate.shipping_days ?? '—')} j</span>
            <span>Coût livré ${esc(money(candidate.landed_cost))}</span>
            <span>eBay US ${esc(money(candidate.reference_price))}</span>
            <span>Ratio coût ${esc(percent(candidate.cost_ratio_percent))}</span>
            <span>Marge ${esc(percent(candidate.margin_percent))}</span>
            <span>Profit ${esc(money(candidate.estimated_profit))}</span>
            <span>Stock route ${esc(candidate.stock ?? '—')}</span>
          </div>
          <small class="seller">Seuil ${candidate.warehouse === 'CN' ? 'Chine' : 'US'} : marge ≥ ${esc(requirements.min_margin_percent ?? '—')} % · profit ≥ ${esc(money(requirements.min_profit))} · stock ≥ ${esc(requirements.min_stock ?? '—')} · délai ≤ ${esc(requirements.max_shipping_days ?? '—')} j</small>
          <div class="panel-actions">${goal}${add}</div>
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
      area.innerHTML = `<strong>Aucun candidat CJ exploitable</strong><span>${esc(error?.message || 'Essayez un autre produit ou une niche plus précise.')}</span>`;
      return;
    }
    const us = candidates.filter(item => item.warehouse === 'US').length;
    const cn = candidates.filter(item => item.warehouse === 'CN').length;
    const eligible = candidates.filter(item => item.route_eligible).length;
    area.className = 'margin-hunter-results';
    area.innerHTML = `${marketSummary(data)}
      <div class="info-box"><strong>${candidates.length} candidat(s) CJ</strong><p>${us} route(s) US · ${cn} route(s) Chine → US · ${eligible} exploitable(s) selon les seuils.</p></div>
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
    if (button) { button.disabled = true; button.textContent = 'Analyse eBay US + CJ…'; }
    area.className = 'loading';
    area.textContent = 'Mesure eBay US puis calcul du coût livré CJ vers les États-Unis…';
    try {
      const response = await fetch('/api/radar/margin-hunter', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({keyword: query, limit: 10}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || `Erreur ${response.status}`);
      renderResults(area, data);
    } catch (error) {
      area.className = 'error-box';
      area.textContent = error.message;
    } finally {
      if (button) { button.disabled = false; button.textContent = previous || 'Chercher les meilleures marges US'; }
    }
  }

  async function addCandidate(id, button) {
    const candidate = candidateStore.get(id);
    if (!candidate?.add_payload || !candidate.route_eligible || !button) return;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = 'Revalidation CJ…';
    try {
      const response = await fetch('/api/supplier-flow/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(candidate.add_payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || `Erreur ${response.status}`);
      button.textContent = 'Ajouté ✓';
      button.classList.remove('primary');
      button.title = data.message || 'Produit ajouté';
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
})();
