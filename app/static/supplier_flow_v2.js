(() => {
  'use strict';

  const offerStore = new Map();
  let counter = 0;

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

  function rememberOffer(item, provider) {
    const id = `flow-${++counter}`;
    offerStore.set(id, {
      provider: String(provider || item.provider || '').toLowerCase(),
      supplier_sku: String(item.supplier_sku || item.sku || item.cj_pid || ''),
      name: item.name || item.title || 'Produit',
      price: Number(item.price ?? item.product_cost ?? item.price_usd ?? 0),
      shipping_cost: item.shipping_cost == null ? null : Number(item.shipping_cost),
      currency: item.currency || (String(provider).toLowerCase() === 'cj' ? 'USD' : 'EUR'),
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
    const id = rememberOffer(item, provider);
    return `<button class="mini-btn primary" data-flow-add="${id}">Ajouter aux Produits</button>`;
  }

  function resultCard(item, provider) {
    const image = item.image_url ? `<img src="${esc(item.image_url)}" alt="" loading="lazy">` : '<div class="image-placeholder">API</div>';
    const link = item.source_url ? `<a class="mini-btn" href="${esc(item.source_url)}" target="_blank" rel="noopener">Voir le produit ↗</a>` : '';
    const price = money(item.price ?? item.product_cost ?? item.price_usd, item.currency || (String(provider).toLowerCase() === 'cj' ? 'USD' : 'EUR'));
    const meta = [
      `Stock ${item.stock ?? '—'}`,
      item.shipping_days == null ? 'Délai —' : `${item.shipping_days} j`,
      item.warehouse || 'Entrepôt inconnu',
    ].map(x => `<span>${esc(x)}</span>`).join('');
    return `<article class="cj-card">${image}<div class="cj-card-body"><h3>${esc(item.name || item.title || 'Produit')}</h3><div class="cj-price">${esc(price)}</div><div class="cj-card-meta">${meta}</div><div class="panel-actions">${addButton(item, provider)}${link}</div></div></article>`;
  }

  function renderCompare(area, data) {
    const groups = data.groups || [];
    const errors = data.errors || [];
    const queried = data.queried || ['CJ', 'Amazon', 'AliExpress'];
    const errorHtml = errors.length
      ? `<div class="warn-box"><strong>${errors.length} source(s) sans résultat</strong><p>${errors.map(x => `${esc(x.source)} : ${esc(x.message)}`).join('<br>')}</p></div>`
      : '';
    const groupHtml = groups.map(group => `
      <section class="supplier-result-group">
        <div class="radar-market-head"><strong>${esc(group.source)}</strong><span>${group.products?.length || 0} offre(s)</span></div>
        <div class="radar-supplier-grid">${(group.products || []).map(item => resultCard(item, group.source)).join('')}</div>
      </section>`).join('');
    area.innerHTML = `<div class="info-box"><strong>${queried.length} fournisseur(s) interrogé(s)</strong><p>${esc(data.note || '')}</p></div>${errorHtml}${groupHtml || '<div class="empty-state compact"><strong>Aucune offre trouvée</strong><span>Vérifiez les connexions fournisseurs ou essayez un autre mot-clé.</span></div>'}`;
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
    button.textContent = 'Ajout…';
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
      button.title = `Produit #${data.product_id} ajouté au dashboard Produits`;
      ensureLegacyCompatibility();
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
            area.innerHTML = '<strong>Aucun résultat</strong><span>Aucune offre trouvée.</span>';
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
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once: true});
  else run();
  setTimeout(run, 500);
  setTimeout(run, 1500);
})();
