(() => {
  'use strict';

  const removedProviders = new Set(['printful', 'printify', 'gelato', 'dropxl', 'etsy']);
  const removedNames = ['printful', 'printify', 'gelato', 'dropxl', 'vidaxl'];
  const namedCardSelector = '.radar-source, .provider-card, .supplier-provider-card, .directory-card, .connection-card';

  function hasRemovedName(node) {
    const text = (node.textContent || '').trim().toLowerCase();
    return removedNames.some(name => text.includes(name));
  }

  function removeNodeIfLegacy(node) {
    if (!(node instanceof Element)) return false;
    const provider = (node.getAttribute('data-provider-card') || '').toLowerCase();
    if (removedProviders.has(provider)) {
      node.remove();
      return true;
    }
    if (node.matches(namedCardSelector) && hasRemovedName(node)) {
      node.remove();
      return true;
    }
    return false;
  }

  function supplierCapabilities(card, text) {
    if (!card || card.querySelector('.supplier-capability-note')) return;
    const note = document.createElement('div');
    note.className = 'supplier-capability-note info-box';
    note.innerHTML = `<strong>Paramètres fournisseur</strong><p>${text}</p>`;
    card.appendChild(note);
  }

  function ensureConnectionSupplierLayout() {
    const section = document.querySelector('#section-connections');
    if (!section) return;
    const heads = [...section.querySelectorAll('.connection-group-head')];
    const catalogHead = heads.find(head => (head.textContent || '').toLowerCase().includes('catalogues et production'));
    if (!catalogHead) return;

    const amazon = section.querySelector('[data-provider-card="amazon"]');
    const cj = section.querySelector('.connection-card-cj');
    if (amazon) {
      catalogHead.insertAdjacentElement('afterend', amazon);
      const kicker = amazon.querySelector('.panel-kicker');
      const paragraph = amazon.querySelector(':scope > p');
      const policy = amazon.querySelector('.policy-note');
      if (kicker) kicker.textContent = 'FOURNISSEUR API';
      if (paragraph) paragraph.textContent = 'Catalogue Amazon France utilisé comme véritable source fournisseur : recherche produit, prix, références et données disponibles alimentent le sourcing.';
      if (policy) policy.textContent = 'Les données Amazon sont normalisées dans le même schéma fournisseur que CJ. Stock, livraison et coût livré restent validés seulement lorsqu’ils sont réellement disponibles.';
      supplierCapabilities(amazon, 'SKU/ASIN · prix · devise · image · entrepôt · stock si disponible · délai/livraison si disponible · analyse de marge.');
    }

    if (cj) {
      const anchor = amazon || catalogHead;
      anchor.insertAdjacentElement('afterend', cj);
      supplierCapabilities(cj, 'SKU · variantes · prix · stock · entrepôt · transport France · délai · coût livré · analyse de marge.');
    }

    const oldAli = [...section.querySelectorAll('.connection-card')].find(card => {
      const title = (card.querySelector('h2')?.textContent || '').trim().toLowerCase();
      return title === 'aliexpress' && !card.classList.contains('native-aliexpress-card');
    });
    oldAli?.remove();

    let ali = section.querySelector('.native-aliexpress-card');
    if (!ali) {
      ali = document.createElement('article');
      ali.className = 'panel connection-card native-aliexpress-card';
      ali.dataset.providerCard = 'aliexpress';
      ali.innerHTML = `
        <div class="panel-head"><div><span class="panel-kicker">FOURNISSEUR API</span><h2>AliExpress</h2></div><span id="connectionStatus-aliexpress" class="status-badge neutral">À connecter</span></div>
        <p>Catalogue AliExpress utilisé comme véritable fournisseur : recherche produit, prix et données logistiques disponibles alimentent le sourcing.</p>
        <form class="form-grid connection-form" data-provider="aliexpress">
          <label>App Key<input name="app_key" type="password" autocomplete="new-password" placeholder="Clé application AliExpress"></label>
          <label>App Secret<input name="app_secret" type="password" autocomplete="new-password" placeholder="Secret application AliExpress"></label>
          <label class="full">Tracking ID <span class="seller">(facultatif)</span><input name="tracking_id" autocomplete="off" placeholder="Tracking ID Affiliate API"></label>
          <div class="full form-actions"><a class="btn btn-ghost" href="https://open.aliexpress.com/" target="_blank" rel="noopener">Configurer l’API ↗</a><button class="btn btn-primary" type="submit">Enregistrer et tester</button></div>
        </form>
        <div id="connectionHelp-aliexpress" class="connection-help">La connexion n’est considérée active qu’après un vrai test API.</div>`;
      supplierCapabilities(ali, 'SKU · prix · devise · image · boutique/entrepôt · stock si disponible · délai/livraison si disponible · analyse de marge.');
    }
    (cj || amazon || catalogHead).insertAdjacentElement('afterend', ali);

    section.querySelectorAll('[data-provider-card="etsy"],[data-provider-card="dropxl"]').forEach(node => node.remove());
  }

  function removeUnwantedSections() {
    document.querySelectorAll('[data-provider-card="etsy"],[data-provider-card="dropxl"]').forEach(node => node.remove());

    const connectionHeads = [...document.querySelectorAll('#section-connections .connection-group-head')];
    connectionHeads.forEach(head => {
      const label = (head.textContent || '').toLowerCase();
      if (label.includes('accès à obtenir') || label.includes('fournisseurs accompagnés') || label.includes('usines')) {
        let node = head.nextElementSibling;
        head.remove();
        while (node && !node.classList.contains('connection-group-head')) {
          const next = node.nextElementSibling;
          node.remove();
          node = next;
        }
      }
    });

    document.querySelector('#section-ebay .sales-channel-panel')?.remove();
    document.querySelector('#section-suppliers .supplier-network')?.remove();
    document.querySelector('#section-suppliers .niche-directory-panel')?.remove();
    document.querySelector('#section-suppliers .supplier-directory')?.remove();
    document.querySelector('#section-suppliers .factory-discovery-panel')?.remove();
    document.querySelector('#section-suppliers .radar-factory-grid')?.remove();
    document.querySelectorAll('#section-suppliers .subsection-head').forEach(head => {
      if ((head.textContent || '').toLowerCase().includes('sourcing direct')) head.remove();
    });

    const radarConnectionPanel = document.querySelector('#section-radar #radarSources')?.closest('.panel');
    radarConnectionPanel?.remove();
  }

  function ensurePipelineSection() {
    if (!document.querySelector('[data-section="pipeline"]')) {
      const radarNav = document.querySelector('[data-section="radar"]');
      if (radarNav) {
        const button = document.createElement('button');
        button.className = 'nav-item';
        button.dataset.section = 'pipeline';
        button.innerHTML = '<span class="nav-icon">⇢</span><span>Pipeline</span>';
        radarNav.insertAdjacentElement('afterend', button);
      }
    }

    if (!document.querySelector('#section-pipeline')) {
      const main = document.querySelector('main.content');
      const section = document.createElement('section');
      section.id = 'section-pipeline';
      section.className = 'page-section';
      section.innerHTML = '<div class="section-head row-between"><div><span class="eyebrow">PIPELINE</span><h1>Pipeline</h1><p>De l’opportunité au brouillon eBay, dans un espace dédié.</p></div></div><div id="pipelineHost"></div>';
      main?.appendChild(section);
    }

    const panel = document.querySelector('#opportunityCenterPanel');
    const host = document.querySelector('#pipelineHost');
    if (panel && host && panel.parentElement !== host) host.appendChild(panel);
  }

  function activatePipeline() {
    document.querySelectorAll('.page-section').forEach(section => section.classList.toggle('active', section.id === 'section-pipeline'));
    document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.section === 'pipeline'));
    const title = document.querySelector('#pageTitle');
    const subtitle = document.querySelector('#pageSubtitle');
    if (title) title.textContent = 'Pipeline';
    if (subtitle) subtitle.textContent = 'Opportunités, fournisseurs, risques et brouillons.';
    document.querySelector('.sidebar')?.classList.remove('open');
    history.replaceState(null, '', '#pipeline');
  }

  function setupPipelineNavigation() {
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-section="pipeline"]');
      if (!button) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      ensurePipelineSection();
      activatePipeline();
    }, true);
    if (location.hash === '#pipeline') setTimeout(activatePipeline, 0);
  }

  function cardHtml(provider) {
    return `<article class="panel supplier-api-panel" data-supplier-pane="${provider}"><form class="search-form supplier-api-search" data-supplier-source="${provider}"><span>⌕</span><input required placeholder="Rechercher un produit sur ${provider === 'amazon' ? 'Amazon' : 'AliExpress'}"><button class="btn btn-primary">Rechercher</button></form><div class="supplier-api-results empty-state compact"><strong>Aucune recherche lancée</strong><span>Les résultats de ce fournisseur apparaîtront ici.</span></div></article>`;
  }

  function renderSupplierResults(area, data) {
    const offers = data.offers || [];
    if (!offers.length) {
      area.className = 'supplier-api-results empty-state compact';
      area.innerHTML = `<strong>Aucun résultat</strong><span>${data.message || 'Aucune offre trouvée.'}</span>`;
      return;
    }
    area.className = 'supplier-api-results cj-product-grid';
    area.innerHTML = offers.map(item => {
      const price = item.product_cost == null ? '—' : `${Number(item.product_cost).toFixed(2)} ${item.currency || 'EUR'}`;
      const image = item.image_url ? `<img src="${item.image_url}" alt="" loading="lazy">` : '<div class="image-placeholder">API</div>';
      const link = item.source_url ? `<a class="mini-btn" href="${item.source_url}" target="_blank" rel="noopener">Voir le produit ↗</a>` : '';
      return `<article class="cj-card">${image}<div class="cj-card-body"><h3>${item.name || 'Produit'}</h3><div class="cj-price">${price}</div><div class="cj-card-meta"><span>Stock ${item.stock ?? '—'}</span><span>${item.shipping_days ?? '—'} j</span><span>${item.warehouse || 'Entrepôt inconnu'}</span></div>${link}</div></article>`;
    }).join('');
  }

  function setupSupplierTabs() {
    const section = document.querySelector('#section-suppliers');
    if (!section || section.querySelector('.supplier-api-tabs')) return;

    const cjHeading = [...section.querySelectorAll('.subsection-head')].find(head => (head.textContent || '').includes('CJ Dropshipping'));
    const cjSearch = document.querySelector('#cjSearchForm')?.closest('.search-panel');
    const cjLayout = document.querySelector('.cj-layout');
    if (!cjSearch || !cjLayout) return;

    const tabs = document.createElement('div');
    tabs.className = 'supplier-api-tabs';
    tabs.innerHTML = '<button class="btn btn-secondary active" data-supplier-tab="cj">CJ</button><button class="btn btn-secondary" data-supplier-tab="amazon">Amazon</button><button class="btn btn-secondary" data-supplier-tab="aliexpress">AliExpress</button>';
    cjHeading?.insertAdjacentElement('beforebegin', tabs);

    const cjPane = document.createElement('div');
    cjPane.dataset.supplierPane = 'cj';
    cjSearch.insertAdjacentElement('beforebegin', cjPane);
    if (cjHeading) cjPane.appendChild(cjHeading);
    cjPane.appendChild(cjSearch);
    cjPane.appendChild(cjLayout);

    const amazonWrap = document.createElement('div');
    amazonWrap.innerHTML = cardHtml('amazon');
    const amazonPane = amazonWrap.firstElementChild;
    amazonPane.hidden = true;
    cjPane.insertAdjacentElement('afterend', amazonPane);

    const aliWrap = document.createElement('div');
    aliWrap.innerHTML = cardHtml('aliexpress');
    const aliPane = aliWrap.firstElementChild;
    aliPane.hidden = true;
    amazonPane.insertAdjacentElement('afterend', aliPane);

    tabs.addEventListener('click', event => {
      const button = event.target.closest('[data-supplier-tab]');
      if (!button) return;
      const selected = button.dataset.supplierTab;
      tabs.querySelectorAll('[data-supplier-tab]').forEach(tab => tab.classList.toggle('active', tab === button));
      section.querySelectorAll('[data-supplier-pane]').forEach(pane => pane.hidden = pane.dataset.supplierPane !== selected);
    });

    section.querySelectorAll('.supplier-api-search').forEach(form => form.addEventListener('submit', async event => {
      event.preventDefault();
      const source = form.dataset.supplierSource;
      const query = form.querySelector('input').value.trim();
      const area = form.parentElement.querySelector('.supplier-api-results');
      area.className = 'supplier-api-results loading';
      area.textContent = 'Recherche en cours…';
      try {
        const response = await fetch(`/api/suppliers/source-search?provider=${encodeURIComponent(source)}&q=${encodeURIComponent(query)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
        renderSupplierResults(area, data);
      } catch (error) {
        area.className = 'supplier-api-results error-box';
        area.textContent = error.message;
      }
    }));
  }

  function cleanup(root = document) {
    if (root instanceof Element && removeNodeIfLegacy(root)) return;
    removedProviders.forEach(provider => root.querySelectorAll?.(`[data-provider-card="${provider}"]`).forEach(node => node.remove()));
    root.querySelectorAll?.(namedCardSelector).forEach(node => { if (hasRemovedName(node)) node.remove(); });
  }

  function runCleanup() {
    ensureConnectionSupplierLayout();
    cleanup(document);
    ensureConnectionSupplierLayout();
    removeUnwantedSections();
    ensurePipelineSection();
    setupSupplierTabs();
    setTimeout(() => {
      ensureConnectionSupplierLayout();
      cleanup(document);
      ensureConnectionSupplierLayout();
      removeUnwantedSections();
      ensurePipelineSection();
      setupSupplierTabs();
    }, 300);
    setTimeout(() => {
      ensureConnectionSupplierLayout();
      ensurePipelineSection();
      setupSupplierTabs();
    }, 1200);
  }

  setupPipelineNavigation();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', runCleanup, { once: true });
  else runCleanup();

  const observer = new MutationObserver(() => {
    ensureConnectionSupplierLayout();
    cleanup(document);
    ensureConnectionSupplierLayout();
    ensurePipelineSection();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();