(() => {
  'use strict';

  const removedProviders = new Set(['printful', 'printify', 'gelato', 'dropxl', 'etsy']);
  const removedNames = ['printful', 'printify', 'gelato', 'dropxl', 'vidaxl'];
  const namedCardSelector = '.radar-source, .provider-card, .supplier-provider-card, .directory-card, .connection-card';

  function hasRemovedName(node) {
    const text = (node.textContent || '').trim().toLowerCase();
    return removedNames.some(name => text.includes(name));
  }

  function cleanupLegacy(root = document) {
    removedProviders.forEach(provider => root.querySelectorAll?.(`[data-provider-card="${provider}"]`).forEach(node => node.remove()));
    root.querySelectorAll?.(namedCardSelector).forEach(node => { if (hasRemovedName(node)) node.remove(); });
  }

  function hideLegacyPanel(node) {
    if (!node) return;
    node.hidden = true;
    node.setAttribute('aria-hidden', 'true');
    node.dataset.legacyHidden = '1';
  }

  function setText(node, value) {
    if (node && node.textContent !== value) node.textContent = value;
  }

  function placeAfter(node, anchor) {
    if (node && anchor && node.previousElementSibling !== anchor) anchor.insertAdjacentElement('afterend', node);
  }

  function supplierCapabilities(card, text) {
    if (!card || card.querySelector('.supplier-capability-note')) return;
    const note = document.createElement('div');
    note.className = 'supplier-capability-note info-box';
    note.innerHTML = `<strong>Paramètres fournisseur</strong><p>${text}</p>`;
    card.appendChild(note);
  }

  function renderAliExpressState(card, connection) {
    if (!card || !connection) return;
    const badge = card.querySelector('#connectionStatus-aliexpress');
    const help = card.querySelector('#connectionHelp-aliexpress');
    if (badge) {
      badge.textContent = connection.status || 'À connecter';
      badge.className = `status-badge ${connection.connected ? 'good' : 'neutral'}`;
    }
    if (!help) return;

    const error = connection.last_error ? `<div class="error-box">${connection.last_error}</div>` : '';
    if (connection.connected) {
      help.innerHTML = `<span>Connexion OAuth vérifiée. AliExpress est disponible dans le sourcing.</span><div><button class="mini-btn" data-test-connection="aliexpress">Tester</button><button class="mini-btn" data-delete-connection="aliexpress">Oublier la connexion</button></div>`;
      return;
    }
    if (connection.configured && !connection.oauth_authorized) {
      help.innerHTML = `${error}<span>Clés enregistrées. Il reste à autoriser votre compte AliExpress.</span><div><button class="mini-btn primary" data-authorize-aliexpress>Autoriser AliExpress</button><button class="mini-btn" data-delete-connection="aliexpress">Oublier les clés</button></div>`;
      return;
    }
    if (connection.configured) {
      help.innerHTML = `${error}<span>Autorisation reçue, mais la connexion Dropshipper doit être retestée.</span><div><button class="mini-btn primary" data-test-connection="aliexpress">Retester</button><button class="mini-btn" data-delete-connection="aliexpress">Oublier la connexion</button></div>`;
      return;
    }
    help.innerHTML = '<span>Étape 1 : enregistrez App Key + App Secret. Étape 2 : autorisez votre compte AliExpress.</span>';
  }

  async function refreshAliExpressState(card) {
    try {
      const response = await fetch('/api/connections');
      const data = await response.json();
      if (!response.ok) return;
      const connection = (data.sources || []).find(row => row.id === 'aliexpress');
      if (connection) renderAliExpressState(card, connection);
    } catch (_) {}
  }

  async function authorizeAliExpress(card) {
    const help = card?.querySelector('#connectionHelp-aliexpress');
    try {
      const response = await fetch('/api/connections/aliexpress/authorize');
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Erreur ${response.status}`);
      if (help) help.innerHTML = `<span>Redirection vers AliExpress…</span><small>URL de retour à déclarer dans l'app AliExpress : ${data.redirect_uri || ''}</small>`;
      window.location.assign(data.authorization_url);
    } catch (error) {
      if (help) help.innerHTML = `<div class="error-box">${error.message}</div>`;
    }
  }

  function bindAliExpressConnection(card) {
    const form = card?.querySelector('.connection-form[data-provider="aliexpress"]');
    if (!form || form.dataset.nativeBound === '1') return;
    form.dataset.nativeBound = '1';
    form.addEventListener('submit', async event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const button = form.querySelector('button[type="submit"]');
      const help = card.querySelector('#connectionHelp-aliexpress');
      const payload = Object.fromEntries(new FormData(form).entries());
      Object.keys(payload).forEach(key => { if (payload[key] === '') delete payload[key]; });
      if (button) { button.disabled = true; button.textContent = 'Enregistrement…'; }
      try {
        const response = await fetch('/api/connections/aliexpress', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Erreur ${response.status}`);
        form.reset();
        renderAliExpressState(card, data.connection);
      } catch (error) {
        if (help) help.innerHTML = `<div class="error-box">${error.message}</div>`;
        await refreshAliExpressState(card);
      } finally {
        if (button) { button.disabled = false; button.textContent = 'Enregistrer les clés'; }
      }
    });
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
      placeAfter(amazon, catalogHead);
      setText(amazon.querySelector('.panel-kicker'), 'FOURNISSEUR API');
      setText(amazon.querySelector(':scope > p'), 'Catalogue Amazon France utilisé comme source fournisseur pour le sourcing et la comparaison des offres.');
      supplierCapabilities(amazon, 'ASIN · prix · devise · image · stock/livraison si disponibles · analyse de marge.');
    }
    if (cj) {
      placeAfter(cj, amazon || catalogHead);
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
        <p>Connexion en 2 étapes : enregistrez les clés de l'application puis autorisez votre compte AliExpress via OAuth.</p>
        <form class="form-grid connection-form" data-provider="aliexpress">
          <label>App Key<input name="app_key" type="password" autocomplete="new-password"></label>
          <label>App Secret<input name="app_secret" type="password" autocomplete="new-password"></label>
          <label class="full">Tracking ID <span class="seller">(facultatif)</span><input name="tracking_id" autocomplete="off"></label>
          <div class="full form-actions"><a class="btn btn-ghost" href="https://open.aliexpress.com/" target="_blank" rel="noopener">Configurer l’API ↗</a><button class="btn btn-primary" type="submit">Enregistrer les clés</button></div>
        </form>
        <div id="connectionHelp-aliexpress" class="connection-help">Étape 1 : enregistrez App Key + App Secret. Étape 2 : autorisez votre compte AliExpress.</div>`;
      supplierCapabilities(ali, 'OAuth AliExpress · API AE-Dropshipper · SKU · prix · devise · image · stock/délai si disponibles · analyse de marge.');
    }
    placeAfter(ali, cj || amazon || catalogHead);
    bindAliExpressConnection(ali);
    refreshAliExpressState(ali);
  }

  function removeUnwantedSections() {
    document.querySelectorAll('[data-provider-card="etsy"],[data-provider-card="dropxl"]').forEach(node => node.remove());
    [...document.querySelectorAll('#section-connections .connection-group-head')].forEach(head => {
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

    // These legacy panels are still referenced by app.js refresh functions.
    // Hide them instead of removing them so background refreshes never dereference null.
    hideLegacyPanel(document.querySelector('#section-ebay .sales-channel-panel'));
    hideLegacyPanel(document.querySelector('#section-suppliers .supplier-network'));
    hideLegacyPanel(document.querySelector('#section-suppliers .niche-directory-panel'));
    hideLegacyPanel(document.querySelector('#section-suppliers .factory-discovery-panel'));
    hideLegacyPanel(document.querySelector('#section-suppliers .radar-factory-grid'));
    document.querySelectorAll('#section-suppliers .subsection-head').forEach(head => {
      if ((head.textContent || '').toLowerCase().includes('sourcing direct')) hideLegacyPanel(head);
    });
    hideLegacyPanel(document.querySelector('#section-radar #radarSources')?.closest('.panel'));

    document.querySelector('[data-section="pipeline"]')?.remove();
    document.querySelector('#section-pipeline')?.remove();
    document.querySelector('#opportunityCenterPanel')?.remove();
  }

  function cardHtml(provider) {
    const label = provider === 'amazon' ? 'Amazon' : 'AliExpress';
    return `<article class="panel supplier-api-panel" data-supplier-pane="${provider}"><form class="search-form supplier-api-search" data-supplier-source="${provider}"><span>⌕</span><input required placeholder="Rechercher un produit sur ${label}"><button class="btn btn-primary">Rechercher</button></form><div class="supplier-api-results empty-state compact"><strong>Aucune recherche lancée</strong><span>Les résultats de ${label} apparaîtront ici.</span></div></article>`;
  }

  function renderSupplierResults(area, data) {
    const offers = data.offers || [];
    if (!offers.length) {
      area.className = 'supplier-api-results empty-state compact';
      area.innerHTML = '<strong>Aucun résultat</strong><span>Aucune offre trouvée.</span>';
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

  function restoreManualSupplierBlock() {
    const section = document.querySelector('#section-suppliers');
    const manual = section?.querySelector('.supplier-directory');
    if (!section || !manual) return;
    manual.hidden = false;
    manual.classList.add('manual-supplier-fallback');
    const kicker = manual.querySelector('.panel-kicker');
    const title = manual.querySelector('h2');
    const text = manual.querySelector('p');
    if (kicker) kicker.textContent = 'SECOURS / FOURNISSEUR PERSONNALISÉ';
    if (title) title.textContent = 'Ajouter un fournisseur manuel ou importer un CSV';
    if (text) text.textContent = 'À utiliser seulement si un fournisseur n’est pas disponible via CJ, Amazon ou AliExpress.';
    section.appendChild(manual);
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-authorize-aliexpress]');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    authorizeAliExpress(document.querySelector('.native-aliexpress-card'));
  }, true);

  function run() {
    ensureConnectionSupplierLayout();
    cleanupLegacy(document);
    removeUnwantedSections();
    setupSupplierTabs();
    restoreManualSupplierBlock();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once: true});
  else run();
  setTimeout(run, 350);
  setTimeout(run, 1200);
})();