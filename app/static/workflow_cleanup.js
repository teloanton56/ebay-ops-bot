(() => {
  'use strict';

  const $ = (q, root = document) => root.querySelector(q);
  const $$ = (q, root = document) => [...root.querySelectorAll(q)];
  const topbarMeta = {
    overview: ['Accueil', 'Vue synthétique du flux dropshipping eBay.'],
    radar: ['Radar marché', 'Détecter et valider la demande.'],
    suppliers: ['Fournisseurs', 'Comparer CJ, Amazon et AliExpress.'],
    pipeline: ['Pipeline', 'Choisir une offre, contrôler marge et risques.'],
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
    const title = $('#pageTitle');
    const subtitle = $('#pageSubtitle');
    if (title) title.textContent = meta[0];
    if (subtitle) subtitle.textContent = meta[1];
  }

  function removeOverviewNoise() {
    const overview = $('#section-overview');
    if (!overview) return;
    $$('.two-col > .panel', overview).forEach(panel => {
      const text = (panel.textContent || '').toLowerCase();
      if (text.includes('checklist de lancement') || text.includes('que voulez-vous faire')) panel.hidden = true;
    });

    const hero = overview.querySelector('.hero');
    if (hero) {
      const eyebrow = hero.querySelector('.eyebrow');
      const title = hero.querySelector('h1');
      const paragraph = hero.querySelector('p');
      if (eyebrow) eyebrow.textContent = 'AUTOMATISATION DROPSHIPPING EBAY';
      if (title) title.textContent = 'Détecter, sourcer, valider et vendre sur eBay.';
      if (paragraph) paragraph.textContent = 'Le bot centralise la recherche produit, compare CJ, Amazon et AliExpress, contrôle la rentabilité puis prépare le passage sur eBay.';
      const actions = hero.querySelector('.hero-actions');
      if (actions) actions.innerHTML = '<button class="btn btn-primary" data-go="radar">1. Trouver un produit</button><button class="btn btn-secondary" data-go="suppliers">2. Comparer les fournisseurs</button>';
    }

    if (!overview.querySelector('.workflow-home')) {
      const stats = overview.querySelector('.stats-grid');
      const workflow = document.createElement('article');
      workflow.className = 'panel workflow-home';
      workflow.innerHTML = `
        <div class="panel-head"><div><span class="panel-kicker">FLUX PRINCIPAL</span><h2>Du produit à la vente eBay</h2><p>Chaque onglet correspond à une étape précise. Pas de doublon entre recherche, sourcing et exécution.</p></div></div>
        <div class="help-flow workflow-home-flow">
          <button data-go="radar"><span>1</span><strong>Radar</strong><small>Détecter et valider la demande</small></button>
          <button data-go="suppliers"><span>2</span><strong>Fournisseurs</strong><small>CJ · Amazon · AliExpress</small></button>
          <button data-section="pipeline"><span>3</span><strong>Pipeline</strong><small>Choisir l'offre et contrôler les risques</small></button>
          <button data-go="catalog"><span>4</span><strong>Produits</strong><small>Catalogue des produits retenus</small></button>
          <button data-go="ebay"><span>5</span><strong>eBay</strong><small>Annonces et commandes</small></button>
          <button data-go="finance"><span>6</span><strong>Pilotage</strong><small>SAV, marge et résultats</small></button>
        </div>`;
      stats?.insertAdjacentElement('afterend', workflow);
    }
  }

  function reorderNavigation() {
    const nav = $('.nav');
    if (!nav) return;
    const order = ['overview', 'radar', 'suppliers', 'pipeline', 'catalog', 'ebay', 'support', 'finance', 'connections', 'settings', 'help'];
    order.forEach(id => {
      const item = nav.querySelector(`[data-section="${id}"]`);
      if (item) nav.appendChild(item);
    });
    const labels = {overview:'Accueil',radar:'Radar marché',suppliers:'Fournisseurs',pipeline:'Pipeline',catalog:'Produits',ebay:'eBay',support:'SAV',finance:'Finance',connections:'Connexions',settings:'Paramètres',help:'Aide'};
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
      const h1 = head.querySelector('h1');
      const p = head.querySelector('p');
      if (h1) h1.textContent = 'Radar marché';
      if (p) p.textContent = 'Détectez une piste, confirmez la demande sur eBay et utilisez Amazon comme signal complémentaire. Le sourcing se fait ensuite dans Fournisseurs.';
    }
    section.querySelector('input[name="radar_source"][value="etsy"]')?.closest('label')?.remove();
    const legend = section.querySelector('.radar-signal-panel legend');
    if (legend) legend.textContent = 'Sources de tendance connectées';
    const signalHead = section.querySelector('.radar-signal-panel h2');
    if (signalHead) signalHead.textContent = 'Confirmer une piste sur les signaux disponibles';
    section.querySelector('.radar-signal-panel .help-tip')?.remove();
    const amazonLegend = section.querySelector('.amazon-markets legend');
    if (amazonLegend) amazonLegend.childNodes[0].textContent = 'Amazon — signal marché complémentaire ';
  }

  function cleanSuppliers() {
    const section = $('#section-suppliers');
    if (!section) return;
    const head = section.querySelector('.section-head');
    if (head) {
      const eyebrow = head.querySelector('.eyebrow');
      const h1 = head.querySelector('h1');
      const p = head.querySelector('p');
      if (eyebrow) eyebrow.textContent = 'SOURCING';
      if (h1) h1.textContent = 'Fournisseurs';
      if (p) p.textContent = 'Recherchez et comparez uniquement CJ Dropshipping, Amazon et AliExpress.';
      head.querySelector('[data-action="add-supplier"]')?.remove();
    }
    section.querySelector('#supplierKpis')?.remove();
    const kicker = section.querySelector('.supplier-match-panel .panel-kicker');
    if (kicker) kicker.textContent = 'COMPARATEUR GLOBAL';
    const matchTitle = section.querySelector('.supplier-match-panel h2');
    const matchText = section.querySelector('.supplier-match-panel p');
    if (matchTitle) matchTitle.textContent = 'Comparer CJ, Amazon et AliExpress';
    if (matchText) matchText.textContent = 'Une seule recherche interroge les trois fournisseurs connectés et regroupe les offres disponibles.';
  }

  function cleanProducts() {
    const section = $('#section-catalog');
    if (!section) return;
    section.querySelector('.opportunity-inbox')?.remove();
    const head = section.querySelector('.section-head');
    if (head) {
      const eyebrow = head.querySelector('.eyebrow');
      const h1 = head.querySelector('h1');
      const p = head.querySelector('p');
      if (eyebrow) eyebrow.textContent = 'CATALOGUE VALIDÉ';
      if (h1) h1.textContent = 'Produits';
      if (p) p.textContent = 'Retrouvez uniquement les produits retenus après sourcing et validation du Pipeline.';
      head.querySelector('[data-action="load-demo"]')?.remove();
    }
  }

  function cleanEbay() {
    const section = $('#section-ebay');
    if (!section) return;
    const head = section.querySelector('.section-head');
    if (head) {
      const eyebrow = head.querySelector('.eyebrow');
      const h1 = head.querySelector('h1');
      const p = head.querySelector('p');
      if (eyebrow) eyebrow.textContent = 'EXÉCUTION EBAY';
      if (h1) h1.textContent = 'eBay';
      if (p) p.textContent = 'Préparez les annonces retenues et suivez les commandes issues d’eBay.';
    }
  }

  function cleanConnections() {
    const section = $('#section-connections');
    if (!section) return;
    const head = section.querySelector('.section-head');
    if (head) {
      const h1 = head.querySelector('h1');
      const p = head.querySelector('p');
      if (h1) h1.textContent = 'Connexions';
      if (p) p.textContent = 'Connectez eBay et les services réellement utilisés par le bot. Les fournisseurs actifs sont CJ, Amazon et AliExpress.';
    }
  }

  function apply() {
    removeOverviewNoise();
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