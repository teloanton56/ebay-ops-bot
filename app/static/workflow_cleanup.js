(() => {
  'use strict';

  const $ = (q, root = document) => root.querySelector(q);
  const $$ = (q, root = document) => [...root.querySelectorAll(q)];
  const topbarMeta = {
    overview: ['Accueil', 'Un seul flux : trouver sur eBay US, sourcer chez CJ, vendre.'],
    radar: ['Radar eBay US', 'Mesurer la demande et la concurrence sur le marché américain.'],
    'shop-spy': ['Spy eBay Shop', 'Analyser une boutique eBay US puis retrouver ses produits chez CJ.'],
    suppliers: ['CJ Dropshipping', 'Un seul fournisseur actif : US warehouse prioritaire, Chine en fallback rentable.'],
    catalog: ['Produits', 'Catalogue eBay US en USD, avec marge et route CJ vérifiées.'],
    ebay: ['eBay US', 'Préparer les annonces et suivre les commandes américaines.'],
    support: ['SAV', 'Suivre les commandes et demandes clients eBay.'],
    finance: ['Finance', 'Suivre chiffre d’affaires, profits et cash généré.'],
    connections: ['Connexions', 'Deux connexions seulement : eBay US et CJ Dropshipping.'],
    settings: ['Paramètres', 'Sécurité, seuils de marge et diagnostic.'],
    help: ['Aide', 'Documentation du bot eBay US / CJ.'],
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
      const text = String(panel.textContent || '').toLowerCase();
      if (text.includes('checklist de lancement') || text.includes('que voulez-vous faire')) panel.hidden = true;
    });
    const hero = overview.querySelector('.hero');
    if (hero) {
      if (hero.querySelector('.eyebrow')) hero.querySelector('.eyebrow').textContent = 'EBAY US · CJ DROPSHIPPING';
      if (hero.querySelector('h1')) hero.querySelector('h1').textContent = 'Trouver un winner, le sourcer chez CJ, le vendre sur eBay US.';
      if (hero.querySelector('p')) hero.querySelector('p').textContent = 'Le bot se concentre sur un seul marché et un seul fournisseur pour générer du cash et valider les produits avant une future montée en puissance sur Shopify.';
      const actions = hero.querySelector('.hero-actions');
      if (actions) actions.innerHTML = '<button class="btn btn-primary" data-go="radar">1. Chercher sur eBay US</button><button class="btn btn-secondary" data-go="suppliers">2. Sourcer avec CJ</button>';
    }

    overview.querySelector('.workflow-home')?.remove();
    const stats = overview.querySelector('.stats-grid');
    if (stats) {
      const workflow = document.createElement('article');
      workflow.className = 'panel workflow-home';
      workflow.innerHTML = `
        <div class="panel-head"><div><span class="panel-kicker">FLUX PRINCIPAL</span><h2>eBay US → CJ → cash-flow</h2><p>Pas de marketplace fournisseur secondaire, pas de réseaux sociaux : uniquement les données nécessaires pour décider.</p></div></div>
        <div class="help-flow workflow-home-flow">
          <button data-go="radar"><span>1</span><strong>Radar US</strong><small>Demande · prix · concurrence</small></button>
          <button data-go="suppliers"><span>2</span><strong>CJ</strong><small>US warehouse puis Chine si rentable</small></button>
          <button data-go="catalog"><span>3</span><strong>Produits</strong><small>Marge · stock · délai · conformité</small></button>
          <button data-go="ebay"><span>4</span><strong>eBay US</strong><small>Annonces · commandes · sync</small></button>
          <button data-go="finance"><span>5</span><strong>Finance</strong><small>Cash et winners à scaler</small></button>
        </div>`;
      stats.insertAdjacentElement('afterend', workflow);
    }
  }

  function reorderNavigation() {
    document.querySelector('[data-section="pipeline"]')?.remove();
    document.querySelector('#section-pipeline')?.remove();
    const nav = $('.nav');
    if (!nav) return;
    const order = ['overview', 'radar', 'shop-spy', 'suppliers', 'catalog', 'ebay', 'support', 'finance', 'connections', 'settings', 'help'];
    order.forEach(id => {
      const item = nav.querySelector(`[data-section="${id}"]`);
      if (item) nav.appendChild(item);
    });
    const labels = {
      overview: 'Accueil', radar: 'Radar US', 'shop-spy': 'Spy eBay Shop', suppliers: 'CJ Dropshipping',
      catalog: 'Produits', ebay: 'eBay US', support: 'SAV', finance: 'Finance',
      connections: 'Connexions', settings: 'Paramètres', help: 'Aide'
    };
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
      if (head.querySelector('h1')) head.querySelector('h1').textContent = 'Radar eBay US';
      if (head.querySelector('p')) head.querySelector('p').textContent = 'Mesurez le prix et la concurrence sur eBay.com, puis passez directement au sourcing CJ.';
    }
    $$('input[name="radar_market"]', section).forEach(input => {
      const keep = input.value === 'EBAY_US';
      input.checked = keep;
      if (!keep) input.closest('label')?.setAttribute('hidden', '');
    });
    $$('input[name="amazon_market"]', section).forEach(input => input.closest('label')?.setAttribute('hidden', ''));
    $$('input[name="radar_source"]', section).forEach(input => input.closest('label')?.setAttribute('hidden', ''));
  }

  function cleanSuppliers() {
    const section = $('#section-suppliers');
    if (!section) return;
    const head = section.querySelector('.section-head');
    if (head) {
      if (head.querySelector('.eyebrow')) head.querySelector('.eyebrow').textContent = 'FOURNISSEUR UNIQUE';
      if (head.querySelector('h1')) head.querySelector('h1').textContent = 'CJ Dropshipping';
      if (head.querySelector('p')) head.querySelector('p').textContent = 'Recherchez le produit chez CJ. Le bot privilégie le stock US et n’utilise la Chine que si la marge compense le délai.';
      head.querySelector('[data-action="add-supplier"]')?.remove();
    }
    const title = section.querySelector('.supplier-match-panel h2');
    const text = section.querySelector('.supplier-match-panel p');
    if (title) title.textContent = 'Rechercher chez CJ';
    if (text) text.textContent = 'Une recherche, un fournisseur. Le coût livré vers les États-Unis est calculé avant ajout.';
  }

  function cleanProducts() {
    const section = $('#section-catalog');
    if (!section) return;
    section.querySelector('.opportunity-inbox')?.setAttribute('hidden', '');
    const head = section.querySelector('.section-head');
    if (head) {
      if (head.querySelector('.eyebrow')) head.querySelector('.eyebrow').textContent = 'CATALOGUE EBAY US';
      if (head.querySelector('h1')) head.querySelector('h1').textContent = 'Produits';
      if (head.querySelector('p')) head.querySelector('p').textContent = 'Uniquement les produits eBay US en USD. Vérifiez marge, route CJ, stock, délai et conformité.';
      head.querySelector('[data-action="load-demo"]')?.remove();
    }
  }

  function cleanEbay() {
    const section = $('#section-ebay');
    const head = section?.querySelector('.section-head');
    if (!head) return;
    if (head.querySelector('.eyebrow')) head.querySelector('.eyebrow').textContent = 'CANAL UNIQUE · EBAY US';
    if (head.querySelector('h1')) head.querySelector('h1').textContent = 'eBay US';
    if (head.querySelector('p')) head.querySelector('p').textContent = 'Préparez et pilotez uniquement les annonces eBay.com en USD.';
  }

  function cleanConnections() {
    const section = $('#section-connections');
    const head = section?.querySelector('.section-head');
    if (!head) return;
    if (head.querySelector('h1')) head.querySelector('h1').textContent = 'Connexions';
    if (head.querySelector('p')) head.querySelector('p').textContent = 'Deux connexions suffisent : votre compte eBay US et CJ Dropshipping.';
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

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, { once: true });
  else apply();
  setTimeout(apply, 400);
  setTimeout(apply, 1200);
})();
