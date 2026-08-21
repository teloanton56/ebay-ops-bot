(() => {
  'use strict';

  const $ = (q, root = document) => root.querySelector(q);
  const $$ = (q, root = document) => [...root.querySelectorAll(q)];
  const topbarMeta = {
    overview: ['Accueil', 'Vue synthétique du flux dropshipping eBay.'],
    radar: ['Radar marché', 'Détecter et valider la demande.'],
    suppliers: ['Fournisseurs', 'Comparer CJ, Amazon et AliExpress, avec import manuel en secours.'],
    catalog: ['Produits', 'Catalogue des produits retenus.'],
    ebay: ['eBay', 'Annonces et commandes.'],
    support: ['SAV', 'Suivi client et litiges.'],
    finance: ['Finance', 'Marge, chiffre d’affaires et résultats.'],
    connections: ['Connexions', 'eBay, CJ, Amazon, AliExpress et signaux marché.'],
    settings: ['Paramètres', 'Règles de marge, sécurité et diagnostic.'],
    help: ['Aide', 'Documentation du bot.'],
  };

  function currentSection() {
    const active = $('.nav-item.active[data-section]');
    return active?.dataset.section || location.hash.replace('#', '') || 'overview';
  }

  function syncTopbar(section = currentSection()) {
    const meta = topbarMeta[section];
    if (!meta) return;
    if ($('#pageTitle')) $('#pageTitle').textContent = meta[0];
    if ($('#pageSubtitle')) $('#pageSubtitle').textContent = meta[1];
  }

  function cleanOverview() {
    const overview = $('#section-overview');
    if (!overview) return;
    $$('.two-col > .panel', overview).forEach(panel => {
      const text = (panel.textContent || '').toLowerCase();
      if (text.includes('checklist de lancement') || text.includes('que voulez-vous faire')) panel.hidden = true;
    });
    const hero = overview.querySelector('.hero');
    if (hero) {
      if (hero.querySelector('.eyebrow')) hero.querySelector('.eyebrow').textContent = 'AUTOMATISATION DROPSHIPPING EBAY';
      if (hero.querySelector('h1')) hero.querySelector('h1').textContent = 'Détecter, sourcer, valider et vendre sur eBay.';
      if (hero.querySelector('p')) hero.querySelector('p').textContent = 'Le bot détecte des opportunités, compare CJ, Amazon et AliExpress, contrôle la rentabilité puis prépare la vente sur eBay.';
      const actions = hero.querySelector('.hero-actions');
      if (actions) actions.innerHTML = '<button class="btn btn-primary" data-go="radar">1. Trouver un produit</button><button class="btn btn-secondary" data-go="suppliers">2. Comparer les fournisseurs</button>';
    }

    overview.querySelector('.workflow-home')?.remove();
    const stats = overview.querySelector('.stats-grid');
    if (stats && !overview.querySelector('.workflow-home')) {
      const workflow = document.createElement('article');
      workflow.className = 'panel workflow-home';
      workflow.innerHTML = `
        <div class="panel-head"><div><span class="panel-kicker">FLUX PRINCIPAL</span><h2>Du produit à la vente eBay</h2><p>Un parcours simple, sans étape intermédiaire inutile.</p></div></div>
        <div class="help-flow workflow-home-flow">
          <button data-go="radar"><span>1</span><strong>Radar</strong><small>Détecter et valider la demande</small></button>
          <button data-go="suppliers"><span>2</span><strong>Fournisseurs</strong><small>CJ · Amazon · AliExpress</small></button>
          <button data-go="catalog"><span>3</span><strong>Produits</strong><small>Valider marge, risques et catalogue</small></button>
          <button data-go="ebay"><span>4</span><strong>eBay</strong><small>Préparer annonces et commandes</small></button>
          <button data-go="support"><span>5</span><strong>SAV</strong><small>Suivre les clients et litiges</small></button>
          <button data-go="finance"><span>6</span><strong>Finance</strong><small>Suivre marges et résultats</small></button>
        </div>`;
      stats.insertAdjacentElement('afterend', workflow);
    }
  }

  function reorderNavigation() {
    document.querySelector('[data-section="pipeline"]')?.remove();
    document.querySelector('#section-pipeline')?.remove();
    const nav = $('.nav');
    if (!nav) return;
    const order = ['overview', 'radar', 'suppliers', 'catalog', 'ebay', 'support', 'finance', 'connections', 'settings', 'help'];
    order.forEach(id => {
      const item = nav.querySelector(`[data-section="${id}"]`);
      if (item) nav.appendChild(item);
    });
    const labels = {overview:'Accueil',radar:'Radar marché',suppliers:'Fournisseurs',catalog:'Produits',ebay:'eBay',support:'SAV',finance:'Finance',connections:'Connexions',settings:'Paramètres',help:'Aide'};
    Object.entries(labels).forEach(([id, label]) => {
      const item = nav.querySelector(`[data-section="${id}"]`);
      const spans = item ? item.querySelectorAll('span') : [];
      if (spans.length >= 2) spans[1].textContent = label;
    });
  }

  function cleanRadar() {
    const section = $('#section-radar');
    if (!section) return;
    const head = section.querySelector('.section-head');
    if (head) {
      if (head.querySelector('h1')) head.querySelector('h1').textContent = 'Radar marché';
      if (head.querySelector('p')) head.querySelector('p').textContent = 'Détectez une piste et confirmez la demande avant de passer au sourcing.';
    }
    section.querySelector('input[name="radar_source"][value="etsy"]')?.closest('label')?.remove();
  }

  function cleanSuppliers() {
    const section = $('#section-suppliers');
    if (!section) return;
    const head = section.querySelector('.section-head');
    if (head) {
      if (head.querySelector('.eyebrow')) head.querySelector('.eyebrow').textContent = 'SOURCING';
      if (head.querySelector('h1')) head.querySelector('h1').textContent = 'Fournisseurs';
      if (head.querySelector('p')) head.querySelector('p').textContent = 'Comparez CJ Dropshipping, Amazon et AliExpress. Ajoutez un fournisseur manuel ou un CSV seulement si nécessaire.';
      head.querySelector('[data-action="add-supplier"]')?.remove();
    }
    section.querySelector('#supplierKpis')?.remove();
    const title = section.querySelector('.supplier-match-panel h2');
    const text = section.querySelector('.supplier-match-panel p');
    if (title) title.textContent = 'Comparer CJ, Amazon et AliExpress';
    if (text) text.textContent = 'Une seule recherche interroge les trois fournisseurs connectés.';
  }

  function cleanProducts() {
    const section = $('#section-catalog');
    if (!section) return;
    section.querySelector('.opportunity-inbox')?.remove();
    const head = section.querySelector('.section-head');
    if (head) {
      if (head.querySelector('.eyebrow')) head.querySelector('.eyebrow').textContent = 'CATALOGUE VALIDÉ';
      if (head.querySelector('h1')) head.querySelector('h1').textContent = 'Produits';
      if (head.querySelector('p')) head.querySelector('p').textContent = 'Validez ici les produits sourcés : marge, stock, délai, risques et préparation eBay.';
      head.querySelector('[data-action="load-demo"]')?.remove();
    }
  }

  function cleanEbay() {
    const section = $('#section-ebay');
    const head = section?.querySelector('.section-head');
    if (!head) return;
    if (head.querySelector('.eyebrow')) head.querySelector('.eyebrow').textContent = 'EXÉCUTION EBAY';
    if (head.querySelector('h1')) head.querySelector('h1').textContent = 'eBay';
    if (head.querySelector('p')) head.querySelector('p').textContent = 'Préparez les annonces retenues et suivez les commandes eBay.';
  }

  function cleanConnections() {
    const section = $('#section-connections');
    const head = section?.querySelector('.section-head');
    if (!head) return;
    if (head.querySelector('h1')) head.querySelector('h1').textContent = 'Connexions';
    if (head.querySelector('p')) head.querySelector('p').textContent = 'Connectez eBay, CJ, Amazon, AliExpress et les sources utilisées par le Radar.';
  }

  function apply() {
    cleanOverview();
    reorderNavigation();
    cleanRadar();
    cleanSuppliers();
    cleanProducts();
    cleanEbay();
    cleanConnections();
    syncTopbar();
  }

  document.addEventListener('click', event => {
    const target = event.target.closest('[data-section],[data-go]');
    const section = target?.dataset.section || target?.dataset.go;
    if (section && topbarMeta[section]) setTimeout(() => syncTopbar(section), 0);
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, {once: true});
  else apply();
  setTimeout(apply, 400);
  setTimeout(apply, 1400);
})();