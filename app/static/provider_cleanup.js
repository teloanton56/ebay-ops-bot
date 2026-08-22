(() => {
  'use strict';

  const retiredNames = [
    'amazon', 'aliexpress', 'tiktok', 'youtube', 'etsy', 'dropxl', 'vidaxl',
    'printful', 'printify', 'gelato', 'google trends', 'meta'
  ];

  function hide(node) {
    if (!node) return;
    node.hidden = true;
    node.setAttribute('aria-hidden', 'true');
    node.dataset.legacyHidden = '1';
  }

  function removeRetiredCards(root = document) {
    root.querySelectorAll?.('[data-provider-card]').forEach(card => {
      const provider = String(card.dataset.providerCard || '').toLowerCase();
      if (retiredNames.includes(provider)) card.remove();
    });
    root.querySelectorAll?.('.connection-card,.provider-card,.supplier-provider-card,.radar-source').forEach(card => {
      const text = String(card.textContent || '').toLowerCase();
      if (retiredNames.some(name => text.includes(name))) card.remove();
    });
  }

  function simplifyConnections() {
    const section = document.querySelector('#section-connections');
    if (!section) return;
    removeRetiredCards(section);

    section.querySelectorAll('.connection-card').forEach(card => {
      const title = String(card.querySelector('h2,h3')?.textContent || card.textContent || '').toLowerCase();
      const isCJ = card.classList.contains('connection-card-cj') || title.includes('cj dropshipping');
      const isEbay = title.includes('ebay');
      if (!isCJ && !isEbay) hide(card);
    });

    // Keep legacy nodes that app.js still touches, but never show multi-source setup.
    section.querySelectorAll('.connection-group-head').forEach(head => {
      const text = String(head.textContent || '').toLowerCase();
      if (text.includes('signaux') || text.includes('catalogues') || text.includes('production') || text.includes('accès')) {
        const visibleUntilNextHead = [];
        let node = head.nextElementSibling;
        while (node && !node.classList.contains('connection-group-head')) {
          if (!node.hidden) visibleUntilNextHead.push(node);
          node = node.nextElementSibling;
        }
        if (!visibleUntilNextHead.length) hide(head);
      }
    });
  }

  function simplifySuppliers() {
    const section = document.querySelector('#section-suppliers');
    if (!section) return;

    // v0.23 has one visible sourcing surface: the CJ comparator/search panel.
    section.querySelector('.supplier-api-tabs')?.remove();
    hide(section.querySelector('#supplierKpis'));
    hide(section.querySelector('.supplier-network'));
    hide(section.querySelector('.niche-directory-panel'));
    hide(section.querySelector('.factory-discovery-panel'));
    hide(section.querySelector('.radar-factory-grid'));
    hide(section.querySelector('.supplier-directory'));
    hide(section.querySelector('.manual-supplier-fallback'));
    hide(section.querySelector('.cj-layout'));
    hide(section.querySelector('#cjSearchForm')?.closest('.search-panel'));

    section.querySelectorAll('.supplier-api-panel').forEach(panel => {
      const source = String(panel.querySelector('form')?.dataset.supplierSource || '').toLowerCase();
      if (source !== 'cj') panel.remove();
    });

    section.querySelectorAll('.subsection-head').forEach(head => {
      const text = String(head.textContent || '').toLowerCase();
      if (text.includes('sourcing direct') || text.includes('annuaire') || text.includes('usine')) hide(head);
      if (text.includes('cj dropshipping') && head.closest('[data-supplier-pane]')) hide(head);
    });
  }

  function simplifyRadar() {
    const section = document.querySelector('#section-radar');
    if (!section) return;
    hide(section.querySelector('#radarSources')?.closest('.panel'));
    hide(section.querySelector('.radar-signal-panel'));
    hide(section.querySelector('.auto-discovery-panel'));
    hide(section.querySelector('#autoRadarPanel'));
    hide(section.querySelector('.tiered-radar-panel'));
    section.querySelectorAll('input[name="radar_source"]').forEach(input => {
      if (input.value !== 'ebay') hide(input.closest('label'));
    });
  }

  function simplifySales() {
    hide(document.querySelector('#section-ebay .sales-channel-panel'));
  }

  function removePipelineRemnants() {
    document.querySelector('[data-section="pipeline"]')?.remove();
    document.querySelector('#section-pipeline')?.remove();
    document.querySelector('#opportunityCenterPanel')?.remove();
  }

  function apply() {
    removeRetiredCards();
    simplifyConnections();
    simplifySuppliers();
    simplifyRadar();
    simplifySales();
    removePipelineRemnants();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, { once: true });
  else apply();
  setTimeout(apply, 400);
  setTimeout(apply, 1200);
})();
