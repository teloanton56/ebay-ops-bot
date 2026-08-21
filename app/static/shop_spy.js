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
    return `${amount.toFixed(2)} ${currency || 'EUR'}`;
  }

  function percent(value) {
    if (value === null || value === undefined || value === '') return 'À confirmer';
    const amount = Number(value);
    return Number.isFinite(amount) ? `${amount.toFixed(1)} %` : 'À confirmer';
  }

  function ensureNav() {
    const nav = document.querySelector('.nav');
    if (!nav) return;
    let button = nav.querySelector('[data-section="shop-spy"]');
    if (!button) {
      button = document.createElement('button');
      button.className = 'nav-item';
      button.dataset.section = 'shop-spy';
      button.innerHTML = '<span class="nav-icon">⌕</span><span>Spy eBay Shop</span>';
    }
    const suppliers = nav.querySelector('[data-section="suppliers"]');
    if (suppliers && button.nextElementSibling !== suppliers) nav.insertBefore(button, suppliers);
    else if (!button.parentElement) nav.appendChild(button);
  }

  function ensureSection() {
    const content = document.querySelector('main.content');
    if (!content || document.querySelector('#section-shop-spy')) return;
    const section = document.createElement('section');
    section.id = 'section-shop-spy';
    section.className = 'page-section';
    section.innerHTML = `
      <div class="section-head row-between">
        <div>
          <span class="eyebrow">CONCURRENCE EBAY</span>
          <h1>Spy eBay Shop</h1>
          <p>Analyse les annonces actives d'un vendeur eBay puis recherche des équivalents chez CJ et AliExpress.</p>
        </div>
        <span class="status-badge neutral">Données eBay réelles</span>
      </div>
      <article class="panel">
        <div class="panel-head">
          <div>
            <span class="panel-kicker">BOUTIQUE À ANALYSER</span>
            <h2>Entrer un vendeur eBay</h2>
            <p>Collez un pseudo vendeur ou une URL de boutique eBay, par exemple <strong>lestylediscount</strong> ou une URL /str/.</p>
          </div>
        </div>
        <form id="shopSpyForm" class="radar-form">
          <label class="full">Pseudo ou URL de boutique
            <input id="shopSpySeller" required placeholder="Ex. lestylediscount ou https://www.ebay.fr/str/lestylediscount">
          </label>
          <label>Nombre d'annonces
            <select id="shopSpyLimit"><option value="25">25</option><option value="50" selected>50</option><option value="100">100</option></select>
          </label>
          <div class="radar-actions"><button class="btn btn-primary" type="submit">Analyser la boutique</button></div>
        </form>
      </article>
      <div id="shopSpyResults" class="empty-state compact">
        <strong>Aucune boutique analysée</strong>
        <span>Le bot utilisera l'API eBay puis pourra comparer chaque annonce à CJ et AliExpress.</span>
      </div>`;
    const suppliers = document.querySelector('#section-suppliers');
    if (suppliers) content.insertBefore(section, suppliers);
    else content.appendChild(section);
  }

  function activate() {
    ensureNav();
    ensureSection();
    document.querySelectorAll('.page-section').forEach(section => section.classList.toggle('active', section.id === 'section-shop-spy'));
    document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.section === 'shop-spy'));
    const title = document.querySelector('#pageTitle');
    const subtitle = document.querySelector('#pageSubtitle');
    if (title) title.textContent = 'Spy eBay Shop';
    if (subtitle) subtitle.textContent = 'Analyser un concurrent eBay puis retrouver ses produits chez les fournisseurs.';
    document.querySelector('.sidebar')?.classList.remove('open');
    history.replaceState(null, '', '#shop-spy');
  }

  function sellerSummary(data) {
    const seller = data.seller || {};
    const feedback = seller.feedback_percent != null
      ? `${esc(seller.feedback_percent)} % · ${esc(seller.feedback_score ?? '—')} évaluations`
      : 'Feedback non fourni';
    const watcherNote = data.watchers_available
      ? 'Watchers disponibles pour certaines annonces'
      : 'Watchers non autorisés/non fournis par eBay';
    return `
      <article class="panel">
        <div class="panel-head"><div><span class="panel-kicker">VENDEUR</span><h2>${esc(seller.username || seller.requested || 'Boutique eBay')}</h2><p>${esc(feedback)}</p></div><span class="status-badge good">${esc(data.active_listings_total || 0)} actives</span></div>
        <div class="stats-grid">
          <article class="stat-card"><div><small>Annonces actives</small><strong>${esc(data.active_listings_total || 0)}</strong><span>échantillon ${esc(data.sample_size || 0)}</span></div></article>
          <article class="stat-card"><div><small>Prix médian</small><strong>${esc(money(data.median_price, data.currency))}</strong><span>${esc(money(data.min_price, data.currency))} → ${esc(money(data.max_price, data.currency))}</span></div></article>
          <article class="stat-card"><div><small>Valeur échantillon</small><strong>${esc(money(data.sample_inventory_value, data.currency))}</strong><span>stock actif, pas CA</span></div></article>
          <article class="stat-card"><div><small>Signal ventes</small><strong>Non exposé</strong><span>${esc(watcherNote)}</span></div></article>
        </div>
        <div class="info-box"><strong>Lecture correcte des données</strong><p>${esc(data.note || '')}</p></div>
      </article>`;
  }

  function listingCard(item) {
    const image = item.image_url
      ? `<img src="${esc(item.image_url)}" alt="" loading="lazy">`
      : '<div class="image-placeholder">eBay</div>';
    const shipping = item.shipping_cost == null ? 'Livraison à vérifier' : `Livraison ${money(item.shipping_cost, item.currency)}`;
    const watchers = item.watch_count == null ? 'Watchers —' : `${item.watch_count} watcher${item.watch_count > 1 ? 's' : ''}`;
    const link = item.item_url
      ? `<a class="mini-btn" href="${esc(item.item_url)}" target="_blank" rel="noopener">Voir eBay ↗</a>`
      : '';
    const compareId = `spy-listing-${esc(item.rank)}`;
    return `
      <article class="cj-card shop-spy-listing">
        ${image}
        <div class="cj-card-body">
          <div class="radar-market-head"><strong>#${esc(item.rank)} · eBay Best Match</strong><span>${esc(watchers)}</span></div>
          <h3>${esc(item.title)}</h3>
          <div class="cj-price">${esc(money(item.price, item.currency))}</div>
          <div class="cj-card-meta"><span>${esc(shipping)}</span><span>Total acheteur ${esc(money(item.buyer_total, item.currency))}</span><span>${esc(item.location_country || 'Pays —')}</span></div>
          <div class="panel-actions"><button class="mini-btn primary" data-spy-compare="${compareId}" data-title="${esc(item.title)}" data-price="${esc(item.price)}">Comparer CJ / AliExpress</button>${link}</div>
          <div id="${compareId}" class="shop-spy-match-area"></div>
        </div>
      </article>`;
  }

  function renderShop(area, data) {
    const listings = data.listings || [];
    area.className = 'shop-spy-results';
    area.innerHTML = `${sellerSummary(data)}
      <article class="panel"><div class="panel-head"><div><span class="panel-kicker">ANNONCES ACTIVES</span><h2>Produits à recouper</h2><p>Ordre renvoyé par eBay. Cliquez sur une annonce pour chercher les équivalents fournisseurs.</p></div></div>
      <div class="radar-supplier-grid">${listings.map(listingCard).join('') || '<div class="empty-state compact"><strong>Aucune annonce trouvée</strong><span>Vérifiez le pseudo eBay.</span></div>'}</div></article>`;
  }

  async function analyze(form) {
    const seller = form.querySelector('#shopSpySeller')?.value.trim();
    const limit = Number(form.querySelector('#shopSpyLimit')?.value || 50);
    const area = document.querySelector('#shopSpyResults');
    if (!seller || !area) return;
    const button = form.querySelector('button[type="submit"]');
    const previous = button?.textContent;
    if (button) { button.disabled = true; button.textContent = 'Analyse eBay…'; }
    area.className = 'loading';
    area.textContent = 'Lecture des annonces actives de la boutique eBay…';
    try {
      const response = await fetch('/api/shop-spy/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({seller, limit}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
      renderShop(area, data);
    } catch (error) {
      area.className = 'error-box';
      area.textContent = error.message;
    } finally {
      if (button) { button.disabled = false; button.textContent = previous || 'Analyser la boutique'; }
    }
  }

  function rememberCandidate(candidate) {
    const id = `spy-candidate-${++candidateCounter}`;
    candidateStore.set(id, candidate);
    return id;
  }

  function supplierCandidate(candidate) {
    const id = rememberCandidate(candidate);
    const image = candidate.image_url
      ? `<img src="${esc(candidate.image_url)}" alt="" loading="lazy">`
      : '<div class="image-placeholder">API</div>';
    const verified = Boolean(candidate.verified);
    const landed = verified ? money(candidate.landed_cost, candidate.currency) : 'À confirmer';
    const margin = verified ? percent(candidate.margin_percent) : `plafond ${percent(candidate.margin_ceiling_percent)}`;
    const shipping = verified
      ? `${money(candidate.shipping_cost, candidate.currency)} · ${candidate.shipping_days ?? '—'} j`
      : `À confirmer · budget max ${money(candidate.shipping_budget_to_30, candidate.currency)}`;
    const source = candidate.source_url
      ? `<a class="mini-btn" href="${esc(candidate.source_url)}" target="_blank" rel="noopener">Voir fournisseur ↗</a>`
      : '';
    return `<article class="cj-card">${image}<div class="cj-card-body"><div class="radar-market-head"><strong>${esc(candidate.provider)}</strong><span class="status-badge ${verified ? 'good' : 'neutral'}">${esc(candidate.verdict || '')}</span></div><h3>${esc(candidate.name || 'Produit')}</h3><div class="cj-price">Coût livré ${esc(landed)}</div><div class="cj-card-meta"><span>Produit ${esc(money(candidate.supplier_cost, candidate.currency))}</span><span>${esc(shipping)}</span><span>Marge ${esc(margin)}</span><span>Ratio ${esc(percent(candidate.cost_ratio_percent))}</span></div><div class="panel-actions"><button class="mini-btn primary" data-spy-add="${id}">Ajouter aux Produits</button>${source}</div></div></article>`;
  }

  async function compareListing(button) {
    const title = button.dataset.title || '';
    const competitorPrice = Number(button.dataset.price || 0);
    const area = document.querySelector(`#${CSS.escape(button.dataset.spyCompare || '')}`);
    if (!title || !competitorPrice || !area) return;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = 'Recherche fournisseurs…';
    area.className = 'loading';
    area.textContent = 'Comparaison du prix eBay avec CJ et AliExpress…';
    try {
      const response = await fetch('/api/shop-spy/compare', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, competitor_price: competitorPrice, limit: 8}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
      const candidates = data.candidates || [];
      const errors = data.errors || [];
      area.className = 'shop-spy-supplier-results';
      area.innerHTML = `<div class="info-box"><strong>Prix concurrent : ${esc(money(data.competitor_price, data.currency))}</strong><p>${esc(data.note || '')}</p></div>${errors.length ? `<div class="warn-box"><p>${errors.map(row => `${esc(row.source)} : ${esc(row.message)}`).join('<br>')}</p></div>` : ''}<div class="radar-supplier-grid">${candidates.map(supplierCandidate).join('') || '<div class="empty-state compact"><strong>Aucun équivalent fiable trouvé</strong></div>'}</div>`;
    } catch (error) {
      area.className = 'error-box';
      area.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = previous;
    }
  }

  async function addCandidate(button) {
    const candidate = candidateStore.get(button.dataset.spyAdd || '');
    if (!candidate?.add_payload) return;
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
      button.title = data.message || 'Produit ajouté aux Produits';
      if (!data.pricing_ready) alert(data.message || 'Produit ajouté, logistique à confirmer.');
    } catch (error) {
      button.disabled = false;
      button.textContent = previous;
      alert(`Ajout impossible : ${error.message}`);
    }
  }

  document.addEventListener('click', event => {
    const nav = event.target.closest('[data-section="shop-spy"], [data-go="shop-spy"]');
    if (nav) {
      event.preventDefault();
      event.stopImmediatePropagation();
      activate();
      return;
    }
    const compare = event.target.closest('[data-spy-compare]');
    if (compare) {
      event.preventDefault();
      compareListing(compare);
      return;
    }
    const add = event.target.closest('[data-spy-add]');
    if (add) {
      event.preventDefault();
      addCandidate(add);
    }
  }, true);

  document.addEventListener('submit', event => {
    const form = event.target.closest('#shopSpyForm');
    if (!form) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    analyze(form);
  }, true);

  function run() {
    ensureNav();
    ensureSection();
    if (window.location.hash === '#shop-spy') activate();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once: true});
  else run();
  setTimeout(run, 600);
  setTimeout(run, 1600);
})();
