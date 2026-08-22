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

  function ensureNav() {
    const nav = document.querySelector('.nav');
    if (!nav) return;
    let button = nav.querySelector('[data-section="shop-spy"]');
    if (!button) {
      button = document.createElement('button');
      button.className = 'nav-item';
      button.dataset.section = 'shop-spy';
      button.innerHTML = '<span class="nav-icon">⌕</span><span>Spy eBay Shop</span>';
      const suppliers = nav.querySelector('[data-section="suppliers"]');
      if (suppliers) nav.insertBefore(button, suppliers);
      else nav.appendChild(button);
    }
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
          <span class="eyebrow">EBAY US · CONCURRENTS</span>
          <h1>Spy eBay Shop</h1>
          <p>Analyse une boutique eBay US puis cherche les mêmes types de produits chez CJ.</p>
        </div>
        <span class="status-badge good">EBAY US → CJ</span>
      </div>
      <article class="panel">
        <div class="panel-head"><div><span class="panel-kicker">BOUTIQUE US</span><h2>Entrer un vendeur eBay</h2><p>Collez un pseudo ou une URL eBay.com /str/.</p></div></div>
        <form id="shopSpyForm" class="radar-form">
          <label class="full">Pseudo ou URL de boutique
            <input id="shopSpySeller" required placeholder="Ex. sellername ou https://www.ebay.com/str/sellername">
          </label>
          <label>Nombre d'annonces
            <select id="shopSpyLimit"><option value="25">25</option><option value="50" selected>50</option><option value="100">100</option></select>
          </label>
          <div class="radar-actions"><button class="btn btn-primary" type="submit">Analyser la boutique US</button></div>
        </form>
      </article>
      <div id="shopSpyResults" class="empty-state compact"><strong>Aucune boutique analysée</strong><span>Le bot lira eBay US puis comparera chaque produit à CJ.</span></div>`;
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
    if (subtitle) subtitle.textContent = 'eBay US → recherche d’équivalents CJ.';
    document.querySelector('.sidebar')?.classList.remove('open');
    history.replaceState(null, '', '#shop-spy');
  }

  function sellerSummary(data) {
    const seller = data.seller || {};
    const feedback = seller.feedback_percent != null
      ? `${esc(seller.feedback_percent)} % · ${esc(seller.feedback_score ?? '—')} évaluations`
      : 'Feedback non fourni';
    return `
      <article class="panel">
        <div class="panel-head"><div><span class="panel-kicker">VENDEUR EBAY US</span><h2>${esc(seller.username || seller.requested || 'Boutique eBay')}</h2><p>${esc(feedback)}</p></div><span class="status-badge good">${esc(data.active_listings_total || 0)} actives</span></div>
        <div class="stats-grid">
          <article class="stat-card"><div><small>Annonces actives</small><strong>${esc(data.active_listings_total || 0)}</strong><span>échantillon ${esc(data.sample_size || 0)}</span></div></article>
          <article class="stat-card"><div><small>Prix médian</small><strong>${esc(money(data.median_price))}</strong><span>${esc(money(data.min_price))} → ${esc(money(data.max_price))}</span></div></article>
          <article class="stat-card"><div><small>Valeur échantillon</small><strong>${esc(money(data.sample_inventory_value))}</strong><span>pas le CA</span></div></article>
          <article class="stat-card"><div><small>Ventes</small><strong>Non exposées</strong><span>aucun chiffre inventé</span></div></article>
        </div>
        <div class="info-box"><p>${esc(data.note || '')}</p></div>
      </article>`;
  }

  function listingCard(item) {
    const image = item.image_url
      ? `<img src="${esc(item.image_url)}" alt="" loading="lazy">`
      : '<div class="image-placeholder">eBay</div>';
    const shipping = item.shipping_cost == null ? 'Shipping —' : `Shipping ${money(item.shipping_cost)}`;
    const watchers = item.watch_count == null ? 'Watchers —' : `${item.watch_count} watcher${item.watch_count > 1 ? 's' : ''}`;
    const link = item.item_url
      ? `<a class="mini-btn" href="${esc(item.item_url)}" target="_blank" rel="noopener">Voir sur eBay ↗</a>`
      : '';
    const compareId = `spy-listing-${esc(item.rank)}`;
    return `
      <article class="cj-card shop-spy-listing">
        ${image}
        <div class="cj-card-body">
          <div class="radar-market-head"><strong>#${esc(item.rank)} · eBay US</strong><span>${esc(watchers)}</span></div>
          <h3>${esc(item.title)}</h3>
          <div class="cj-price">${esc(money(item.price))}</div>
          <div class="cj-card-meta"><span>${esc(shipping)}</span><span>Total ${esc(money(item.buyer_total))}</span><span>Ships from ${esc(item.location_country || '—')}</span></div>
          <div class="panel-actions"><button class="mini-btn primary" data-spy-compare="${compareId}" data-title="${esc(item.title)}" data-price="${esc(item.price)}">Comparer avec CJ</button>${link}</div>
          <div id="${compareId}" class="shop-spy-match-area"></div>
        </div>
      </article>`;
  }

  function renderShop(area, data) {
    const listings = data.listings || [];
    area.className = 'shop-spy-results';
    area.innerHTML = `${sellerSummary(data)}
      <article class="panel"><div class="panel-head"><div><span class="panel-kicker">ANNONCES ACTIVES US</span><h2>Produits à recouper chez CJ</h2><p>Le prix concurrent sert de référence de marge, pas de preuve de ventes.</p></div></div>
      <div class="radar-supplier-grid">${listings.map(listingCard).join('') || '<div class="empty-state compact"><strong>Aucune annonce USD trouvée</strong><span>Vérifiez le vendeur eBay US.</span></div>'}</div></article>`;
  }

  async function analyze(form) {
    const seller = form.querySelector('#shopSpySeller')?.value.trim();
    const limit = Number(form.querySelector('#shopSpyLimit')?.value || 50);
    const area = document.querySelector('#shopSpyResults');
    if (!seller || !area) return;
    const button = form.querySelector('button[type="submit"]');
    const previous = button?.textContent;
    if (button) { button.disabled = true; button.textContent = 'Analyse eBay US…'; }
    area.className = 'loading';
    area.textContent = 'Lecture des annonces actives eBay US…';
    try {
      const response = await fetch('/api/shop-spy/analyze', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({seller, limit}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || `Erreur ${response.status}`);
      renderShop(area, data);
    } catch (error) {
      area.className = 'error-box';
      area.textContent = error.message;
    } finally {
      if (button) { button.disabled = false; button.textContent = previous || 'Analyser la boutique US'; }
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
      : '<div class="image-placeholder">CJ</div>';
    const route = candidate.route || (candidate.warehouse === 'US' ? 'CJ US' : 'CJ China → US');
    const add = candidate.route_eligible
      ? `<button class="mini-btn primary" data-spy-add="${id}">Ajouter aux Produits</button>`
      : '<span class="candidate-pending">Hors seuils · ne pas lancer</span>';
    return `<article class="cj-card">${image}<div class="cj-card-body">
      <div class="radar-market-head"><strong>${esc(route)}</strong><span class="status-badge ${candidate.warehouse === 'US' ? 'good' : 'neutral'}">${esc(candidate.verdict || '')}</span></div>
      <h3>${esc(candidate.name || 'CJ product')}</h3>
      <div class="cj-price">Coût livré ${esc(money(candidate.landed_cost))}</div>
      <div class="cj-card-meta"><span>Produit ${esc(money(candidate.supplier_cost))}</span><span>Transport ${esc(money(candidate.shipping_cost))} · ${esc(candidate.shipping_days ?? '—')} j</span><span>Marge ${esc(percent(candidate.margin_percent))}</span><span>Profit ${esc(money(candidate.estimated_profit))}</span><span>Ratio ${esc(percent(candidate.cost_ratio_percent))}</span></div>
      <div class="panel-actions">${add}</div>
    </div></article>`;
  }

  async function compareListing(button) {
    const title = button.dataset.title || '';
    const competitorPrice = Number(button.dataset.price || 0);
    const area = document.querySelector(`#${CSS.escape(button.dataset.spyCompare || '')}`);
    if (!title || !competitorPrice || !area) return;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = 'Recherche CJ…';
    area.className = 'loading';
    area.textContent = 'Recherche CJ puis calcul du coût livré vers les États-Unis…';
    try {
      const response = await fetch('/api/shop-spy/compare', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, competitor_price: competitorPrice, limit: 8}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || `Erreur ${response.status}`);
      const candidates = data.candidates || [];
      const errors = data.errors || [];
      area.className = 'shop-spy-supplier-results';
      area.innerHTML = `<div class="info-box"><strong>Prix eBay US : ${esc(money(data.competitor_price))}</strong><p>${esc(data.note || '')}</p></div>${errors.length ? `<div class="warn-box"><p>${errors.map(row => `${esc(row.source)} : ${esc(row.message)}`).join('<br>')}</p></div>` : ''}<div class="radar-supplier-grid">${candidates.map(supplierCandidate).join('') || '<div class="empty-state compact"><strong>Aucun équivalent CJ fiable trouvé</strong></div>'}</div>`;
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
    if (!candidate?.add_payload || !candidate.route_eligible) return;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = 'Revalidation CJ…';
    try {
      const response = await fetch('/api/supplier-flow/add', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(candidate.add_payload),
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

  document.addEventListener('click', event => {
    const nav = event.target.closest('[data-section="shop-spy"], [data-go="shop-spy"]');
    if (nav) { event.preventDefault(); event.stopImmediatePropagation(); activate(); return; }
    const compare = event.target.closest('[data-spy-compare]');
    if (compare) { event.preventDefault(); compareListing(compare); return; }
    const add = event.target.closest('[data-spy-add]');
    if (add) { event.preventDefault(); addCandidate(add); }
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
  setTimeout(run, 500);
})();
