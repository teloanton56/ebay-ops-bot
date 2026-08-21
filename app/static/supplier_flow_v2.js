(() => {
  'use strict';

  const offerStore = new Map();
  let counter = 0;
  let catalogObserver = null;

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));

  function ensureLegacyCompatibility() {
    const ids = ['supplierDirectoryNote', 'supplierDirectoryResults'];
    ids.forEach(id => {
      if (document.getElementById(id)) return;
      const node = document.createElement('div');
      node.id = id;
      node.hidden = true;
      node.setAttribute('aria-hidden', 'true');
      document.body.appendChild(node);
    });
  }

  function money(value, currency = 'EUR') {
    if (value === null || value === undefined || value === '') return 'Prix à vérifier';
    const amount = Number(value);
    if (!Number.isFinite(amount)) return 'Prix à vérifier';
    return `${amount.toFixed(2)} ${currency || 'EUR'}`;
  }

  function providerCode(provider) {
    return String(provider || '').trim().toLowerCase();
  }

  function rememberOffer(item, provider) {
    const id = `flow-${++counter}`;
    const code = providerCode(provider || item.provider);
    offerStore.set(id, {
      provider: code,
      supplier_sku: String(item.supplier_sku || item.sku || item.cj_pid || ''),
      cj_pid: String(item.cj_pid || ''),
      name: item.name || item.title || 'Produit',
      price: Number(item.price ?? item.product_cost ?? item.price_usd ?? 0),
      shipping_cost: item.shipping_cost == null ? null : Number(item.shipping_cost),
      currency: item.currency || (code === 'cj' ? 'USD' : 'EUR'),
      stock: item.stock == null ? null : Number(item.stock),
      shipping_days: item.shipping_days == null ? null : Number(item.shipping_days),
      image_url: item.image_url || '',
      source_url: item.source_url || '',
    });
    return id;
  }

  function addButton(item, provider) {
    const price = item.price ?? item.product_cost ?? item.price_usd;
    const sku = item.supplier_sku || item.sku || item.cj_pid;
    if (price === null || price === undefined || !sku) {
      return '<span class="candidate-pending">Prix ou SKU à vérifier avant ajout</span>';
    }
    const code = providerCode(provider || item.provider);
    const id = rememberOffer(item, provider);
    const label = code === 'cj' ? 'Calculer livraison & ajouter' : 'Ajouter aux Produits';
    return `<button class="mini-btn primary" data-flow-add="${id}" data-flow-provider="${esc(code)}">${label}</button>`;
  }

  function resultCard(item, provider) {
    const code = providerCode(provider || item.provider);
    const image = item.image_url ? `<img src="${esc(item.image_url)}" alt="" loading="lazy">` : '<div class="image-placeholder">API</div>';
    const link = item.source_url ? `<a class="mini-btn" href="${esc(item.source_url)}" target="_blank" rel="noopener">Voir le produit ↗</a>` : '';
    const price = money(item.price ?? item.product_cost ?? item.price_usd, item.currency || (code === 'cj' ? 'USD' : 'EUR'));
    const shippingLabel = code === 'cj'
      ? 'Transport calculé à l’ajout'
      : (item.shipping_cost == null ? 'Livraison à confirmer' : `Livraison ${money(item.shipping_cost, item.currency || 'EUR')}`);
    const relevance = Number(item.match_strength);
    const relevanceLabel = Number.isFinite(relevance) && relevance > 0
      ? `Pertinence ${Math.round(relevance * 100)}%`
      : null;
    const meta = [
      relevanceLabel,
      `Stock ${item.stock ?? '—'}`,
      item.shipping_days == null ? 'Délai —' : `${item.shipping_days} j`,
      shippingLabel,
    ].filter(Boolean).map(x => `<span>${esc(x)}</span>`).join('');
    return `<article class="cj-card">${image}<div class="cj-card-body"><h3>${esc(item.name || item.title || 'Produit')}</h3><div class="cj-price">${esc(price)}</div><div class="cj-card-meta">${meta}</div><div class="panel-actions">${addButton(item, provider)}${link}</div></div></article>`;
  }

  function renderCompare(area, data) {
    const groups = data.groups || [];
    const errors = data.errors || [];
    const queried = data.queried || ['CJ', 'Amazon', 'AliExpress'];
    const errorHtml = errors.length
      ? `<div class="warn-box"><strong>${errors.length} source(s) sans résultat pertinent</strong><p>${errors.map(x => `${esc(x.source)} : ${esc(x.message)}`).join('<br>')}</p></div>`
      : '';
    const groupHtml = groups.map(group => {
      const filtered = Number(group.filtered_out || 0);
      const countLabel = `${group.products?.length || 0} offre(s) pertinente(s)${filtered > 0 ? ` · ${filtered} hors sujet masqué(s)` : ''}`;
      return `
        <section class="supplier-result-group">
          <div class="radar-market-head"><strong>${esc(group.source)}</strong><span>${esc(countLabel)}</span></div>
          <div class="radar-supplier-grid">${(group.products || []).map(item => resultCard(item, group.source)).join('')}</div>
        </section>`;
    }).join('');
    area.innerHTML = `<div class="info-box"><strong>${queried.length} fournisseur(s) interrogé(s)</strong><p>${esc(data.note || '')}</p></div>${errorHtml}${groupHtml || '<div class="empty-state compact"><strong>Aucun produit pertinent trouvé</strong><span>Essayez un mot-clé plus précis ou un autre produit.</span></div>'}`;
  }

  async function compareSuppliers(form) {
    const input = form.querySelector('input');
    const q = input?.value.trim();
    const area = document.querySelector('#supplierMatchResults');
    if (!q || !area) return;
    area.className = '';
    area.innerHTML = '<div class="loading">Comparaison de CJ, Amazon et AliExpress…</div>';
    try {
      const response = await fetch(`/api/supplier-flow/compare?q=${encodeURIComponent(q)}`);
      const data = await response.json();
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
    button.textContent = offer.provider === 'cj' ? 'Calcul transport…' : 'Ajout…';
    try {
      const response = await fetch('/api/supplier-flow/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(offer),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
      button.textContent = 'Ajouté ✓';
      button.classList.remove('primary');
      button.title = data.message || `Produit #${data.product_id} ajouté au dashboard Produits`;
      ensureLegacyCompatibility();
      if (!data.pricing_ready) {
        alert(data.message || 'Produit ajouté, mais la livraison et le prix conseillé restent à confirmer.');
      }
    } catch (error) {
      button.disabled = false;
      button.textContent = previous;
      alert(`Ajout impossible : ${error.message}`);
    }
  }

  function enhanceCatalogResults() {
    document.querySelectorAll('.supplier-api-panel').forEach(panel => {
      if (panel.dataset.flowEnhanced === '1') return;
      panel.dataset.flowEnhanced = '1';
      const form = panel.querySelector('.supplier-api-search');
      if (!form) return;
      form.addEventListener('submit', async event => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const source = form.dataset.supplierSource;
        const q = form.querySelector('input')?.value.trim();
        const area = panel.querySelector('.supplier-api-results');
        if (!q || !area) return;
        area.className = 'supplier-api-results loading';
        area.textContent = 'Recherche en cours…';
        try {
          const response = await fetch(`/api/suppliers/source-search?provider=${encodeURIComponent(source)}&q=${encodeURIComponent(q)}`);
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
          const offers = data.offers || [];
          if (!offers.length) {
            area.className = 'supplier-api-results empty-state compact';
            area.innerHTML = '<strong>Aucun résultat pertinent</strong><span>Aucune offre réellement liée à cette recherche.</span>';
            return;
          }
          area.className = 'supplier-api-results cj-product-grid';
          area.innerHTML = offers.map(item => resultCard(item, source)).join('');
        } catch (error) {
          area.className = 'supplier-api-results error-box';
          area.textContent = error.message;
        }
      }, true);
    });
  }

  function normalizeProductCatalogPresentation() {
    const body = document.querySelector('#productTableBody');
    if (!body) return;
    body.querySelectorAll('tr').forEach(row => {
      const cells = row.querySelectorAll('td');
      if (cells.length < 6) return;
      const supplierCell = cells[1];
      const priceCell = cells[2];
      const providerText = (supplierCell.textContent || '').toLowerCase();
      const managedSupplier = providerText.includes('cj dropshipping') || providerText.includes('aliexpress') || providerText.includes('amazon france');
      const priceStrong = priceCell.querySelector('strong');
      const targetHint = priceCell.querySelector('.seller');
      const targetMissing = (priceStrong?.textContent || '').trim() === '—' || (targetHint?.textContent || '').includes('Cible —');
      if (!targetMissing) return;

      if (priceStrong && priceStrong.textContent !== 'À calculer') priceStrong.textContent = 'À calculer';
      const supplierMeta = supplierCell.querySelector('.seller');
      if (managedSupplier && supplierMeta && !supplierMeta.textContent.includes('livraison à confirmer')) {
        const parts = supplierMeta.textContent.split('+');
        if (parts.length >= 2) supplierMeta.textContent = `${parts[0].trim()} + livraison à confirmer`;
      }
    });
  }

  function watchProductCatalog() {
    const body = document.querySelector('#productTableBody');
    if (!body) return;
    normalizeProductCatalogPresentation();
    if (catalogObserver) catalogObserver.disconnect();
    catalogObserver = new MutationObserver(() => normalizeProductCatalogPresentation());
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
    if (button) {
      event.preventDefault();
      addOffer(button.dataset.flowAdd, button);
    }
  });

  const run = () => {
    ensureLegacyCompatibility();
    enhanceCatalogResults();
    watchProductCatalog();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once: true});
  else run();
  setTimeout(run, 500);
  setTimeout(run, 1500);
})();
