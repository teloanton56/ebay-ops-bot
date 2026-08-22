(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { summary: null, radarKeyword: '', radarMarket: null, products: [] };

  const titles = {
    overview: ['Vue d’ensemble', 'Un seul marché, un seul fournisseur, un workflow clair.'],
    radar: ['Radar eBay US', 'Mesurer le marché avant de chercher un fournisseur.'],
    suppliers: ['CJ Dropshipping', 'Calculer le vrai coût livré aux États-Unis.'],
    catalog: ['Produits', 'Garder uniquement les produits eBay US / USD validés.'],
    ebay: ['eBay US', 'Préparer les produits validés avant publication.'],
    support: ['SAV', 'Gérer les incidents après les premières commandes.'],
    finance: ['Finance', 'Suivre les ventes et la rentabilité réelle.'],
    settings: ['Connexions', 'Seulement eBay US et CJ Dropshipping.'],
  };

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
    if (!response.ok) {
      const message = data && typeof data === 'object' ? (data.detail || data.message) : data;
      throw new Error(message || `Erreur HTTP ${response.status}`);
    }
    return data;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  }

  function money(value) {
    const number = Number(value);
    return Number.isFinite(number) ? `$${number.toFixed(2)}` : '—';
  }

  function toast(message, error = false) {
    const node = $('#toast');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('error', error);
    node.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove('show'), 3200);
  }

  function show(section) {
    $$('.page-section').forEach(node => node.classList.toggle('active', node.id === `section-${section}`));
    $$('.nav-item').forEach(node => node.classList.toggle('active', node.dataset.section === section));
    const [title, subtitle] = titles[section] || titles.overview;
    $('#pageTitle').textContent = title;
    $('#pageSubtitle').textContent = subtitle;
    document.body.classList.remove('sidebar-open');
    if (section === 'catalog') loadProducts();
    if (section === 'support') loadSupport();
    if (section === 'finance') loadFinance();
  }

  function setConnectedChip(selector, connected, label) {
    const chip = $(selector);
    if (!chip) return;
    chip.classList.toggle('connected', Boolean(connected));
    const text = $('span:last-child', chip);
    if (text) text.textContent = label;
  }

  async function loadSummary() {
    try {
      const [summary, cj, ebay] = await Promise.all([
        api('/api/ui/summary'), api('/api/cj/settings'), api('/api/settings/ebay'),
      ]);
      state.summary = summary;
      $('#statProducts').textContent = summary.products ?? 0;
      $('#statPass').textContent = summary.risk_pass ?? 0;
      $('#navProductCount').textContent = summary.products ?? 0;
      $('#statCj').textContent = cj.connected ? 'Connecté' : 'À connecter';
      setConnectedChip('#cjChip', cj.connected, cj.connected ? 'CJ connecté' : 'CJ à connecter');
      setConnectedChip('#ebayChip', ebay.connected, ebay.connected ? 'eBay connecté' : 'eBay à connecter');
      $('#cjConnectionText').textContent = cj.connected
        ? 'Connecté. Les calculs de fret sont verrouillés vers les États-Unis.'
        : 'Connectez CJ pour rechercher des produits et calculer leur coût livré US.';
      $('#ebayConnectionText').textContent = ebay.connected
        ? 'Compte eBay connecté en mode US.'
        : (ebay.configured ? 'Clés configurées. Autorisez maintenant le compte eBay.' : 'Ajoutez vos clés eBay Production puis connectez le compte.');
      updateNextStep();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function updateNextStep() {
    const products = Number(state.summary?.products || 0);
    const cjConnected = $('#cjChip')?.classList.contains('connected');
    const title = $('#nextStepTitle');
    const text = $('#nextStepText');
    const button = $('#nextStepButton');
    if (!cjConnected) {
      title.textContent = 'Connectez CJ Dropshipping';
      text.textContent = 'Le Radar peut mesurer eBay US, mais le calcul de coût livré nécessite CJ.';
      button.textContent = 'Ouvrir les connexions';
      button.dataset.go = 'settings';
    } else if (products === 0) {
      title.textContent = 'Trouvez votre premier produit';
      text.textContent = 'Mesurez une niche eBay US puis validez son coût livré chez CJ.';
      button.textContent = 'Lancer une analyse Radar';
      button.dataset.go = 'radar';
    } else {
      title.textContent = 'Analysez le prochain candidat';
      text.textContent = 'Continuez à alimenter le catalogue avec des produits mesurés et rentables.';
      button.textContent = 'Retour au Radar';
      button.dataset.go = 'radar';
    }
  }

  function renderRadar(market, keyword) {
    const target = $('#radarResults');
    const items = market.items || [];
    target.className = '';
    target.innerHTML = `
      <div class="simple-card-grid">
        <article class="simple-result-card">
          <span class="panel-kicker">MARCHÉ MESURÉ</span>
          <h3>${escapeHtml(keyword)}</h3>
          <div class="metrics">
            <div class="metric"><small>Annonces actives</small><strong>${escapeHtml(market.total_results ?? 0)}</strong></div>
            <div class="metric"><small>Prix médian</small><strong>${money(market.median_price)}</strong></div>
            <div class="metric"><small>Prix minimum</small><strong>${money(market.min_price)}</strong></div>
            <div class="metric"><small>Devise</small><strong>USD</strong></div>
          </div>
          <p>Données : eBay US uniquement. Le volume exact de recherches n’est pas fourni par eBay.</p>
          <div class="card-actions"><button class="btn btn-primary" data-search-cj="${escapeHtml(keyword)}">Chercher sur CJ</button></div>
        </article>
        ${items.slice(0, 4).map(item => `
          <article class="simple-result-card">
            ${item.image_url ? `<img src="${escapeHtml(item.image_url)}" alt="">` : ''}
            <h3>${escapeHtml(item.title)}</h3>
            <div class="status-line"><strong>${money(item.price?.value)}</strong><span>${escapeHtml(item.seller || '')}</span></div>
          </article>`).join('')}
      </div>`;
  }

  async function runRadar(event) {
    event.preventDefault();
    const keyword = $('#radarQuery').value.trim();
    if (keyword.length < 2) return;
    state.radarKeyword = keyword;
    $('#radarResults').className = 'loading-inline';
    $('#radarResults').textContent = 'Analyse eBay US en cours…';
    try {
      const data = await api('/api/radar/scan', { method: 'POST', body: JSON.stringify({ keyword }) });
      const market = data.markets?.[0] || {};
      state.radarMarket = market;
      renderRadar(market, keyword);
    } catch (error) {
      $('#radarResults').className = 'empty-state compact guided-empty';
      $('#radarResults').innerHTML = `<strong>Analyse impossible</strong><span>${escapeHtml(error.message)}</span>`;
    }
  }

  function renderCjSearch(products) {
    const target = $('#cjResults');
    if (!products.length) {
      target.className = 'empty-state compact guided-empty';
      target.innerHTML = '<strong>Aucun résultat CJ pertinent</strong><span>Essayez un terme produit plus précis.</span>';
      return;
    }
    target.className = 'simple-card-grid';
    target.innerHTML = products.map((product, index) => `
      <article class="simple-result-card">
        ${product.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : ''}
        <h3>${escapeHtml(product.name)}</h3>
        <div class="metrics">
          <div class="metric"><small>Prix indicatif</small><strong>${money(product.price_usd)}</strong></div>
          <div class="metric"><small>Stock annoncé</small><strong>${escapeHtml(product.stock ?? 0)}</strong></div>
        </div>
        <p>Le prix fournisseur seul n’est pas utilisé pour décider. Le bot doit d’abord calculer le transport réel vers les États-Unis.</p>
        <button class="btn btn-primary" data-cj-index="${index}">Calculer le coût livré US</button>
      </article>`).join('');
    target._products = products;
  }

  async function searchCj(event) {
    event.preventDefault();
    const keyword = $('#cjQuery').value.trim();
    if (keyword.length < 2) return;
    $('#cjResults').className = 'loading-inline';
    $('#cjResults').textContent = 'Recherche CJ en cours…';
    try {
      const result = await api(`/api/cj/products?q=${encodeURIComponent(keyword)}&size=12&min_stock=1`);
      renderCjSearch(result.products || []);
    } catch (error) {
      $('#cjResults').className = 'empty-state compact guided-empty';
      $('#cjResults').innerHTML = `<strong>Recherche CJ impossible</strong><span>${escapeHtml(error.message)}</span><button class="btn btn-soft" type="button" data-go="settings">Vérifier la connexion CJ</button>`;
    }
  }

  async function analyzeCj(product, card) {
    const button = $('[data-cj-index]', card);
    button.disabled = true;
    button.textContent = 'Calcul US…';
    try {
      const selected = await api('/api/cj/candidates', {
        method: 'POST',
        body: JSON.stringify({
          cj_pid: product.cj_pid,
          sku: product.sku || '',
          name: product.name,
          image_url: product.image_url || '',
          price_usd: Number(product.price_usd || 0),
          category_name: product.category_name || '',
          stock: Number(product.stock || 0),
          warehouse_country: product.warehouse_country || '',
          delivery_cycle: product.delivery_cycle || '',
        }),
      });
      const result = await api(`/api/cj/candidates/${selected.candidate_id}/analyze`, {
        method: 'POST', body: JSON.stringify({ destination_country: 'US' }),
      });
      const a = result.analysis || {};
      card.innerHTML = `
        ${product.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : ''}
        <span class="panel-kicker">COÛT US VÉRIFIÉ</span>
        <h3>${escapeHtml(product.name)}</h3>
        <div class="metrics">
          <div class="metric"><small>Route</small><strong>${escapeHtml(a.route || 'CJ')}</strong></div>
          <div class="metric"><small>Destination</small><strong>US</strong></div>
          <div class="metric"><small>Produit</small><strong>${money(a.supplier_cost_usd)}</strong></div>
          <div class="metric"><small>Transport</small><strong>${money(a.shipping_cost_usd)}</strong></div>
          <div class="metric"><small>Coût livré</small><strong>${money(a.landed_cost_usd)}</strong></div>
          <div class="metric"><small>Délai</small><strong>${escapeHtml(a.shipping?.delivery_days || '—')}</strong></div>
        </div>
        <p>Devise : USD · Destination : United States. Ce coût sera revalidé avant publication.</p>
        <button class="btn btn-primary" data-add-candidate="${selected.candidate_id}">Ajouter aux Produits</button>`;
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Réessayer le calcul US';
      toast(error.message, true);
    }
  }

  async function addCandidate(candidateId, button) {
    button.disabled = true;
    try {
      await api(`/api/cj/candidates/${candidateId}/add-product`, { method: 'POST', body: '{}' });
      toast('Produit ajouté au catalogue eBay US.');
      await loadSummary();
      await loadProducts();
      show('catalog');
    } catch (error) {
      button.disabled = false;
      toast(error.message, true);
    }
  }

  async function loadProducts() {
    const target = $('#productList');
    target.className = 'loading-inline';
    target.textContent = 'Chargement des produits…';
    try {
      const products = await api('/api/products');
      state.products = products || [];
      $('#navProductCount').textContent = products.length;
      if (!products.length) {
        target.className = 'empty-state guided-empty';
        target.innerHTML = '<strong>Aucun produit validé</strong><span>Commencez par mesurer le marché puis validez un coût livré CJ.</span><button class="btn btn-primary" type="button" data-go="radar">Lancer une analyse Radar</button>';
        $('#ebayState').className = 'empty-state guided-empty';
        return;
      }
      target.className = 'simple-card-grid';
      target.innerHTML = products.map(product => {
        const risk = product.risk || {};
        return `<article class="simple-result-card">
          <span class="panel-kicker">${risk.pass ? 'VALIDÉ' : 'À CORRIGER'}</span>
          <h3>${escapeHtml(product.title)}</h3>
          <div class="metrics">
            <div class="metric"><small>Prix cible</small><strong>${money(product.target_price)}</strong></div>
            <div class="metric"><small>Coût livré</small><strong>${money(Number(product.supplier_cost || 0) + Number(product.shipping_cost || 0))}</strong></div>
            <div class="metric"><small>Stock</small><strong>${escapeHtml(product.stock ?? 0)}</strong></div>
            <div class="metric"><small>Délai</small><strong>${escapeHtml(product.shipping_days ?? 0)} j</strong></div>
          </div>
          <p>${risk.pass ? 'Risk Engine OK. Revalidation CJ requise avant toute écriture eBay.' : escapeHtml((risk.blocks || []).join(' · ') || 'Validation incomplète.')}</p>
          <div class="card-actions">${risk.pass ? `<button class="btn btn-primary" data-prepare-product="${product.id}">Préparer eBay US</button>` : ''}</div>
        </article>`;
      }).join('');
      renderEbayReady(products);
    } catch (error) {
      target.className = 'empty-state guided-empty';
      target.innerHTML = `<strong>Catalogue indisponible</strong><span>${escapeHtml(error.message)}</span>`;
    }
  }

  function renderEbayReady(products) {
    const ready = products.filter(product => product.risk?.pass);
    const target = $('#ebayState');
    if (!ready.length) {
      target.className = 'empty-state guided-empty';
      target.innerHTML = '<strong>Aucun produit prêt à publier</strong><span>Validez d’abord un produit CJ rentable dans le catalogue.</span><button class="btn btn-primary" type="button" data-go="catalog">Voir les produits</button>';
      return;
    }
    target.className = 'simple-card-grid';
    target.innerHTML = ready.map(product => `<article class="simple-result-card"><span class="panel-kicker">PRÊT À REVALIDER</span><h3>${escapeHtml(product.title)}</h3><p>Avant publication, le bot doit recontrôler stock, fret, marge et localisation CJ.</p><button class="btn btn-primary" data-prepare-product="${product.id}">Préparer eBay US</button></article>`).join('');
  }

  async function prepareProduct(productId, button) {
    button.disabled = true;
    try {
      const result = await api(`/api/products/${productId}/prepare-ebay`, { method: 'POST', body: '{}' });
      toast(result.message || 'Brouillon eBay US préparé.');
      button.textContent = 'Préparé';
    } catch (error) {
      button.disabled = false;
      toast(error.message, true);
    }
  }

  async function loadSupport() {
    try {
      const data = await api('/api/support/cases');
      const rows = data.cases || [];
      if (!rows.length) return;
      $('#supportState').className = 'simple-card-grid';
      $('#supportState').innerHTML = rows.slice(0, 8).map(row => `<article class="simple-result-card"><span class="panel-kicker">${escapeHtml(row.status)}</span><h3>${escapeHtml(row.subject)}</h3><p>${escapeHtml(row.category)}</p></article>`).join('');
    } catch (_) {}
  }

  async function loadFinance() {
    try {
      const data = await api('/api/finance/summary?days=30&target=5000');
      const target = $('#financeState');
      const sales = Number(data.orders || data.sales || 0);
      if (!sales) return;
      target.className = 'simple-card-grid';
      target.innerHTML = `<article class="simple-result-card"><span class="panel-kicker">30 JOURS</span><h3>Performance eBay US</h3><div class="metrics"><div class="metric"><small>Commandes</small><strong>${sales}</strong></div><div class="metric"><small>CA</small><strong>${money(data.revenue)}</strong></div></div></article>`;
    } catch (_) {}
  }

  async function configureCj() {
    const key = window.prompt('Collez votre clé API CJ Dropshipping :');
    if (!key) return;
    try {
      await api('/api/cj/settings', { method: 'POST', body: JSON.stringify({ api_key: key.trim() }) });
      toast('CJ connecté.');
      await loadSummary();
    } catch (error) { toast(error.message, true); }
  }

  async function configureEbay() {
    const current = await api('/api/settings/ebay');
    if (current.configured) {
      location.href = '/api/auth/ebay/start';
      return;
    }
    const clientId = window.prompt('eBay Production Client ID :');
    if (!clientId) return;
    const clientSecret = window.prompt('eBay Production Client Secret :');
    if (!clientSecret) return;
    const runame = window.prompt('eBay RuName :');
    if (!runame) return;
    try {
      await api('/api/settings/ebay', { method: 'POST', body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, runame, environment: 'production', marketplace_id: 'EBAY_US', currency: 'USD' }) });
      location.href = '/api/auth/ebay/start';
    } catch (error) { toast(error.message, true); }
  }

  document.addEventListener('click', event => {
    const go = event.target.closest('[data-go]');
    if (go) { event.preventDefault(); show(go.dataset.go); return; }
    const nav = event.target.closest('[data-section]');
    if (nav) { show(nav.dataset.section); return; }
    const cjSearch = event.target.closest('[data-search-cj]');
    if (cjSearch) { $('#cjQuery').value = cjSearch.dataset.searchCj; show('suppliers'); $('#cjSearchForm').requestSubmit(); return; }
    const cjButton = event.target.closest('[data-cj-index]');
    if (cjButton) { const root = $('#cjResults'); const product = root._products?.[Number(cjButton.dataset.cjIndex)]; if (product) analyzeCj(product, cjButton.closest('.simple-result-card')); return; }
    const add = event.target.closest('[data-add-candidate]');
    if (add) { addCandidate(add.dataset.addCandidate, add); return; }
    const prepare = event.target.closest('[data-prepare-product]');
    if (prepare) { prepareProduct(prepare.dataset.prepareProduct, prepare); return; }
    if (event.target.closest('[data-action="configure-cj"]')) { configureCj(); return; }
    if (event.target.closest('[data-action="connect-ebay"]')) { configureEbay(); return; }
  });

  $('#mobileMenu')?.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
  $('#radarForm')?.addEventListener('submit', runRadar);
  $('#cjSearchForm')?.addEventListener('submit', searchCj);
  $('#refreshProducts')?.addEventListener('click', loadProducts);

  loadSummary();
  loadProducts();
})();
