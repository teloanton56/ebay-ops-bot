(() => {
  'use strict';

  const offerStore = new Map();
  let counter = 0;
  let catalogObserver = null;

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));

  function money(value) {
    if (value === null || value === undefined || value === '') return 'À vérifier';
    const amount = Number(value);
    return Number.isFinite(amount) ? `$${amount.toFixed(2)}` : 'À vérifier';
  }

  function rememberOffer(item) {
    const id = `flow-${++counter}`;
    offerStore.set(id, {
      provider: 'cj',
      supplier_sku: String(item.supplier_sku || item.sku || item.cj_pid || ''),
      cj_pid: String(item.cj_pid || ''),
      name: item.name || item.title || 'CJ product',
      price: Number(item.price ?? item.product_cost ?? item.price_usd ?? 0),
      shipping_cost: null,
      currency: 'USD',
      stock: item.stock == null ? null : Number(item.stock),
      shipping_days: null,
      image_url: item.image_url || '',
      source_url: item.source_url || '',
    });
    return id;
  }

  function addButton(item) {
    const price = item.price ?? item.product_cost ?? item.price_usd;
    const sku = item.supplier_sku || item.sku || item.cj_pid;
    if (price === null || price === undefined || !sku || !item.cj_pid) {
      return '<span class="candidate-pending">Produit CJ incomplet</span>';
    }
    const id = rememberOffer(item);
    return `<button class="mini-btn primary" data-flow-add="${id}">Calculer route US/CN & ajouter</button>`;
  }

  function resultCard(item) {
    const image = item.image_url
      ? `<img src="${esc(item.image_url)}" alt="" loading="lazy">`
      : '<div class="image-placeholder">CJ</div>';
    const relevance = Number(item.match_strength);
    const relevanceLabel = Number.isFinite(relevance) && relevance > 0
      ? `Pertinence ${Math.round(relevance * 100)}%`
      : null;
    const meta = [
      relevanceLabel,
      `Stock catalogue ${item.stock ?? '—'}`,
      'US warehouse prioritaire',
      'Chine seulement si rentable',
    ].filter(Boolean).map(x => `<span>${esc(x)}</span>`).join('');
    return `<article class="cj-card">${image}<div class="cj-card-body">
      <h3>${esc(item.name || item.title || 'CJ product')}</h3>
      <div class="cj-price">Catalogue ${esc(money(item.price ?? item.product_cost ?? item.price_usd))}</div>
      <div class="cj-card-meta">${meta}</div>
      <div class="panel-actions">${addButton(item)}</div>
    </div></article>`;
  }

  function renderCompare(area, data) {
    const groups = data.groups || [];
    const errors = data.errors || [];
    const errorHtml = errors.length
      ? `<div class="warn-box"><p>${errors.map(x => `${esc(x.source || 'CJ')} : ${esc(x.message)}`).join('<br>')}</p></div>`
      : '';
    const group = groups[0];
    const cards = (group?.products || []).map(resultCard).join('');
    const filtered = Number(group?.filtered_out || 0);
    const sourceTotal = Number(group?.source_total || 0);
    const sampled = Number(group?.sampled || 0);
    const shown = Number(group?.products?.length || 0);
    const coverage = sourceTotal > 0
      ? `${sourceTotal.toLocaleString('fr-FR')} correspondance(s) CJ · ${sampled} analysée(s) · ${filtered} hors sujet masqué(s)`
      : (filtered ? `${filtered} hors sujet masqué(s)` : 'USD · destination US');
    area.innerHTML = `
      <div class="info-box"><strong>CJ Dropshipping · eBay US</strong><p>${esc(data.note || 'US warehouse prioritaire, Chine en fallback rentable.')}</p></div>
      ${errorHtml}
      ${group ? `<div class="radar-market-head"><strong>${shown} résultat(s) affiché(s)</strong><span>${esc(coverage)}</span></div>` : ''}
      <div class="radar-supplier-grid">${cards || '<div class="empty-state compact"><strong>Aucun produit CJ pertinent</strong><span>Essayez une recherche plus précise.</span></div>'}</div>`;
  }

  async function compareSuppliers(form) {
    const q = form.querySelector('input')?.value.trim();
    const area = document.querySelector('#supplierMatchResults');
    if (!q || !area) return;
    area.className = '';
    area.innerHTML = '<div class="loading">Recherche élargie du catalogue CJ…</div>';
    try {
      const response = await fetch(`/api/supplier-flow/compare?q=${encodeURIComponent(q)}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
      renderCompare(area, data);
    } catch (error) {
      area.innerHTML = `<div class="error-box">${esc(error.message)}</div>`;
    }
  }

  async function addOffer(id, button) {
    const offer = offerStore.get(id);
    if (!offer) return;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = 'Inventaire CJ + routes transport…';
    try {
      const response = await fetch('/api/supplier-flow/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(offer),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || `Erreur ${response.status}`);
      button.textContent = 'Ajouté ✓';
      button.classList.remove('primary');
      button.title = data.message || 'Produit ajouté';
      const route = data.route || (data.warehouse === 'US' ? 'CJ US' : 'CJ China → US');
      alert(`${data.message || 'Produit ajouté.'}\nRoute retenue : ${route}`);
    } catch (error) {
      button.disabled = false;
      button.textContent = previous;
      alert(`Ajout impossible : ${error.message}`);
    }
  }

  function normalizeProductCatalogPresentation() {
    const body = document.querySelector('#productTableBody');
    if (!body) return;
    body.querySelectorAll('tr').forEach(row => {
      const cells = row.querySelectorAll('td');
      if (cells.length < 6) return;
      const supplierCell = cells[1];
      const priceCell = cells[2];
      const providerText = String(supplierCell.textContent || '').toLowerCase();
      if (!providerText.includes('cj')) return;
      const priceStrong = priceCell.querySelector('strong');
      const targetHint = priceCell.querySelector('.seller');
      const targetMissing = (priceStrong?.textContent || '').trim() === '—' || (targetHint?.textContent || '').includes('Cible —');
      if (targetMissing && priceStrong) priceStrong.textContent = 'À calculer';
      const riskText = cells[5].querySelector('.seller');
      if (riskText) riskText.textContent = riskText.textContent.replace('Risk ', 'Risk US ');
    });
  }

  function watchProductCatalog() {
    const body = document.querySelector('#productTableBody');
    if (!body) return;
    normalizeProductCatalogPresentation();
    catalogObserver?.disconnect();
    catalogObserver = new MutationObserver(normalizeProductCatalogPresentation);
    catalogObserver.observe(body, {childList: true, subtree: true});
  }

  document.addEventListener('submit', event => {
    const form = event.target.closest('#supplierMatchForm');
    if (!form) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    compareSuppliers(form);
  }, true);

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-flow-add]');
    if (!button) return;
    event.preventDefault();
    addOffer(button.dataset.flowAdd, button);
  });

  const run = () => watchProductCatalog();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once: true});
  else run();
  setTimeout(run, 500);
})();
