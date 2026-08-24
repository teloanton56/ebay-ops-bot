(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { summary: null, radarKeyword: '', radarMarket: null, radarResearch: null, products: [] };

  const titles = {
    overview: ['Vue d’ensemble', 'Trouver, décider, importer, préparer.'],
    radar: ['Radar eBay US', 'Comprendre le potentiel en un coup d’œil.'],
    suppliers: ['CJ Dropshipping', 'Analyser et importer sans quitter l’écran.'],
    catalog: ['Produits', 'Marge réelle, SEO et préparation eBay au même endroit.'],
    ebay: ['eBay US', 'Préparer uniquement les produits validés.'],
    support: ['SAV', 'Gérer les incidents après les premières commandes.'],
    finance: ['Finance', 'Suivre les ventes et la rentabilité réelle.'],
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

  function percent(value) {
    const number = Number(value);
    return Number.isFinite(number) ? `${number.toFixed(1)}%` : '—';
  }

  function toneFromScore(score) {
    const value = Number(score || 0);
    if (value >= 70) return 'good';
    if (value >= 50) return 'warn';
    return 'bad';
  }

  function marginTone(margin) {
    const value = Number(margin);
    if (!Number.isFinite(value)) return 'neutral';
    if (value >= 30) return 'good';
    if (value >= 20) return 'warn';
    return 'bad';
  }

  function competitionTone(label) {
    const value = String(label || '').toLowerCase();
    if (value.includes('faible')) return 'good';
    if (value.includes('modérée')) return 'warn';
    if (value.includes('élevée') || value.includes('extrême')) return 'bad';
    return 'neutral';
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
      title.textContent = 'CJ Dropshipping doit être disponible';
      text.textContent = 'La clé CJ se configure côté serveur. Une fois active, recherchez un produit pour vérifier sa marge réelle.';
      button.textContent = 'Ouvrir CJ Dropshipping';
      button.dataset.go = 'suppliers';
    } else if (products === 0) {
      title.textContent = 'Trouvez votre premier produit';
      text.textContent = 'Analysez une niche, puis importez un candidat CJ en un clic.';
      button.textContent = 'Lancer le Radar';
      button.dataset.go = 'radar';
    } else {
      title.textContent = 'Trouvez le prochain winner';
      text.textContent = 'Le bot doit vous aider à décider vite : potentiel, marge, SEO, puis préparation eBay.';
      button.textContent = 'Retour au Radar';
      button.dataset.go = 'radar';
    }
  }

  function radarVerdict(summary) {
    const score = Number(summary?.score || 0);
    if (score >= 70) return 'Fort potentiel marché';
    if (score >= 50) return 'À creuser';
    return score >= 30 ? 'Prudence' : 'Faible potentiel';
  }

  function renderRadar(market, keyword, summary) {
    const target = $('#radarResults');
    const items = market.items || [];
    const score = Number(summary?.score || 0);
    const tone = toneFromScore(score);
    const competition = summary?.competition?.label || 'Non mesurée';
    const history = summary?.trend?.label || 'Premier relevé';
    target.className = '';
    target.innerHTML = `
      <div class="decision-layout">
        <article class="decision-card ${tone}">
          <div class="score-gauge ${tone}" style="--score:${Math.max(0, Math.min(score, 100))}">
            <div><strong>${score}</strong><span>/100</span></div>
          </div>
          <div class="decision-copy">
            <span class="panel-kicker">POTENTIEL MARCHÉ</span>
            <h2>${escapeHtml(radarVerdict(summary))}</h2>
            <p>Score de structure eBay US : concurrence, concentration, prix et historique. La rentabilité réelle est confirmée seulement après calcul CJ.</p>
          </div>
          <div class="signal-grid">
            <div class="signal neutral"><small>Demande</small><strong>À confirmer</strong><span>eBay n’expose pas le volume exact</span></div>
            <div class="signal ${competitionTone(competition)}"><small>Concurrence</small><strong>${escapeHtml(competition)}</strong><span>${escapeHtml(market.total_results ?? 0)} annonces actives</span></div>
            <div class="signal neutral"><small>Rentabilité</small><strong>À vérifier</strong><span>Calcul CJ all-inclusive requis</span></div>
          </div>
          <div class="decision-reasons">
            <span>Prix médian <strong>${money(market.median_price)}</strong></span>
            <span>${escapeHtml(history)}</span>
            <span>eBay US · USD</span>
          </div>
          <button class="btn btn-primary decision-cta" data-search-cj="${escapeHtml(keyword)}">Vérifier la marge chez CJ</button>
        </article>

        <div class="simple-card-grid market-listings">
          ${items.slice(0, 4).map(item => `
            <article class="simple-result-card market-card">
              ${item.image_url ? `<img src="${escapeHtml(item.image_url)}" alt="">` : ''}
              <h3>${escapeHtml(item.title)}</h3>
              <div class="status-line"><strong>${money(item.price?.value)}</strong><span>${escapeHtml(item.seller || '')}</span></div>
            </article>`).join('')}
        </div>
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
      state.radarResearch = data.research_summary || {};
      renderRadar(market, keyword, state.radarResearch);
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
      <article class="simple-result-card cj-card">
        ${product.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : ''}
        <h3>${escapeHtml(product.name)}</h3>
        <div class="metrics">
          <div class="metric"><small>Prix indicatif</small><strong>${money(product.price_usd)}</strong></div>
          <div class="metric"><small>Stock annoncé</small><strong>${escapeHtml(product.stock ?? 0)}</strong></div>
        </div>
        <p>Un clic : route US/CN, fret réel vers les US, marge complète, variante et import catalogue.</p>
        <button class="btn btn-primary" data-cj-import-index="${index}">Analyser + importer</button>
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
      $('#cjResults').innerHTML = `<strong>Recherche CJ impossible</strong><span>${escapeHtml(error.message)}</span>`;
    }
  }

  function marginSummary(profit, feeModel = {}) {
    if (!profit || profit.sale_price == null) return '';
    const tone = marginTone(profit.margin_percent);
    return `
      <div class="margin-box ${tone}">
        <div class="margin-main">
          <div><small>Profit net estimé</small><strong>${money(profit.estimated_profit)}</strong></div>
          <div><small>Marge nette</small><strong>${percent(profit.margin_percent)}</strong></div>
          <div><small>ROI</small><strong>${percent(profit.roi_percent)}</strong></div>
        </div>
        <div class="margin-flow"><span>Vente ${money(profit.sale_price)}</span><b>→</b><span>Coûts ${money(profit.total_estimated_cost)}</span><b>→</b><strong>${money(profit.estimated_profit)}</strong></div>
        <details>
          <summary>Voir le calcul all-inclusive</summary>
          <div class="fee-lines">
            <span><small>Produit CJ</small><strong>${money(profit.supplier_cost)}</strong></span>
            <span><small>Transport CJ</small><strong>${money(profit.shipping_cost)}</strong></span>
            <span><small>Frais eBay ${escapeHtml(feeModel.ebay_fee_percent ?? '')}%</small><strong>${money(profit.estimated_ebay_fee)}</strong></span>
            <span><small>Promoted Listings ${escapeHtml(feeModel.promoted_listings_percent ?? '')}%</small><strong>${money(profit.estimated_ad_fee)}</strong></span>
            <span><small>Réserve retours ${escapeHtml(feeModel.return_reserve_percent ?? '')}%</small><strong>${money(profit.returns_reserve)}</strong></span>
            <span><small>Frais commande</small><strong>${money(profit.fixed_fee)}</strong></span>
            <span><small>Break-even</small><strong>${money(profit.break_even_price)}</strong></span>
          </div>
        </details>
      </div>`;
  }

  function observedKeywords() {
    const values = [];
    if (state.radarKeyword) values.push(state.radarKeyword);
    (state.radarMarket?.items || []).slice(0, 3).forEach(item => {
      if (item.title) values.push(item.title);
    });
    return values.slice(0, 4);
  }

  async function quickImportCj(product, card) {
    const button = $('[data-cj-import-index]', card);
    button.disabled = true;
    button.textContent = 'Analyse US + import…';
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
      const analyzed = await api(`/api/cj/candidates/${selected.candidate_id}/analyze`, {
        method: 'POST', body: JSON.stringify({ destination_country: 'US' }),
      });
      const added = await api(`/api/cj/candidates/${selected.candidate_id}/add-product`, { method: 'POST', body: '{}' });
      const catalogProduct = await api(`/api/products/${added.product_id}`);
      const a = analyzed.analysis || {};
      const productScore = Number(state.radarResearch?.score || 0);
      const margin = Number(catalogProduct.profit?.margin_percent || 0);
      const combined = Math.max(0, Math.min(100, Math.round(productScore * 0.45 + Math.min(margin / 40 * 100, 100) * 0.45 + (a.route === 'CJ US' ? 10 : 5))));
      const tone = toneFromScore(combined);
      card.classList.add('imported-card');
      card.innerHTML = `
        ${product.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="">` : ''}
        <div class="import-success"><span>✓</span><div><strong>Importé</strong><small>${escapeHtml(a.route || 'CJ')} → eBay US</small></div></div>
        <h3>${escapeHtml(catalogProduct.title)}</h3>
        <div class="mini-score ${tone}"><strong>${combined}/100</strong><span>Potentiel produit</span></div>
        <div class="metrics">
          <div class="metric"><small>Coût livré</small><strong>${money(a.landed_cost_usd)}</strong></div>
          <div class="metric"><small>Délai</small><strong>${escapeHtml(a.shipping?.delivery_days || '—')}</strong></div>
        </div>
        ${marginSummary(catalogProduct.profit, catalogProduct.fee_model)}
        <div class="card-actions">
          <button class="btn btn-primary" data-optimize-product="${catalogProduct.id}">Optimiser pour eBay</button>
          <button class="btn btn-soft" data-go="catalog">Voir dans Produits</button>
        </div>`;
      toast('Produit analysé et importé.');
      await loadSummary();
      await loadProducts();
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Réessayer';
      toast(error.message, true);
    }
  }

  async function optimizeProduct(productId, button) {
    button.disabled = true;
    button.textContent = 'Optimisation…';
    try {
      const result = await api(`/api/products/${productId}/optimize-ebay`, {
        method: 'POST',
        body: JSON.stringify({ market_keywords: observedKeywords() }),
      });
      toast(`Titre optimisé : ${result.optimized_title}`);
      button.textContent = 'SEO optimisé ✓';
      await loadProducts();
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Optimiser pour eBay';
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
        target.innerHTML = '<strong>Aucun produit validé</strong><span>Commencez par le Radar puis utilisez “Analyser + importer” chez CJ.</span><button class="btn btn-primary" type="button" data-go="radar">Lancer le Radar</button>';
        $('#ebayState').className = 'empty-state guided-empty';
        return;
      }
      target.className = 'simple-card-grid product-grid';
      target.innerHTML = products.map(product => {
        const risk = product.risk || {};
        const profit = product.profit || {};
        const marginClass = marginTone(profit.margin_percent);
        return `<article class="simple-result-card product-decision-card">
          <div class="card-topline"><span class="status-pill ${risk.pass ? 'good' : 'bad'}">${risk.pass ? 'VALIDÉ' : 'À CORRIGER'}</span><span class="status-pill ${marginClass}">${profit.margin_percent != null ? `${percent(profit.margin_percent)} marge` : 'Marge à calculer'}</span></div>
          <h3>${escapeHtml(product.title)}</h3>
          <div class="metrics">
            <div class="metric"><small>Prix cible</small><strong>${money(product.target_price)}</strong></div>
            <div class="metric"><small>Coût livré</small><strong>${money(profit.landed_cost)}</strong></div>
            <div class="metric"><small>Stock</small><strong>${escapeHtml(product.stock ?? 0)}</strong></div>
            <div class="metric"><small>Délai</small><strong>${escapeHtml(product.shipping_days ?? 0)} j</strong></div>
          </div>
          ${marginSummary(profit, product.fee_model)}
          <p>${risk.pass ? 'Risk Engine OK. CJ sera revalidé avant toute publication réelle.' : escapeHtml((risk.blocks || []).join(' · ') || 'Validation incomplète.')}</p>
          <div class="card-actions">
            <button class="btn btn-soft" data-optimize-product="${product.id}">Optimiser pour eBay</button>
            ${risk.pass ? `<button class="btn btn-primary" data-prepare-product="${product.id}">Préparer eBay US</button>` : ''}
          </div>
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
      target.innerHTML = '<strong>Aucun produit prêt à publier</strong><span>Validez d’abord un produit CJ rentable.</span><button class="btn btn-primary" type="button" data-go="catalog">Voir les produits</button>';
      return;
    }
    target.className = 'simple-card-grid';
    target.innerHTML = ready.map(product => `<article class="simple-result-card"><span class="panel-kicker">PRÊT À REVALIDER</span><h3>${escapeHtml(product.title)}</h3>${marginSummary(product.profit, product.fee_model)}<div class="card-actions"><button class="btn btn-soft" data-optimize-product="${product.id}">Optimiser SEO</button><button class="btn btn-primary" data-prepare-product="${product.id}">Préparer eBay US</button></div></article>`).join('');
  }

  async function prepareProduct(productId, button) {
    button.disabled = true;
    try {
      const result = await api(`/api/products/${productId}/prepare-ebay`, { method: 'POST', body: '{}' });
      toast(result.message || 'Brouillon eBay US préparé.');
      button.textContent = 'Préparé ✓';
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

  document.addEventListener('click', event => {
    const go = event.target.closest('[data-go]');
    if (go) { event.preventDefault(); show(go.dataset.go); return; }
    const nav = event.target.closest('[data-section]');
    if (nav) { show(nav.dataset.section); return; }
    const cjSearch = event.target.closest('[data-search-cj]');
    if (cjSearch) { $('#cjQuery').value = cjSearch.dataset.searchCj; show('suppliers'); $('#cjSearchForm').requestSubmit(); return; }
    const quickImport = event.target.closest('[data-cj-import-index]');
    if (quickImport) {
      const root = $('#cjResults');
      const product = root._products?.[Number(quickImport.dataset.cjImportIndex)];
      if (product) quickImportCj(product, quickImport.closest('.simple-result-card'));
      return;
    }
    const optimize = event.target.closest('[data-optimize-product]');
    if (optimize) { optimizeProduct(optimize.dataset.optimizeProduct, optimize); return; }
    const prepare = event.target.closest('[data-prepare-product]');
    if (prepare) { prepareProduct(prepare.dataset.prepareProduct, prepare); return; }
  });

  $('#mobileMenu')?.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
  $('#radarForm')?.addEventListener('submit', runRadar);
  $('#cjSearchForm')?.addEventListener('submit', searchCj);
  $('#refreshProducts')?.addEventListener('click', loadProducts);

  loadSummary();
  loadProducts();
})();
