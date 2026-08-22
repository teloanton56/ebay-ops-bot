(() => {
  'use strict';

  const retiredNames = [
    'amazon', 'aliexpress', 'tiktok', 'youtube', 'etsy', 'dropxl', 'vidaxl',
    'printful', 'printify', 'gelato', 'google trends', 'meta'
  ];
  let supplierFilterObserver = null;
  let modalObserver = null;

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
      const keep = card.classList.contains('connection-card-cj') || title.includes('cj dropshipping') || title.includes('ebay');
      if (!keep) hide(card);
    });
  }

  function simplifySuppliers() {
    const section = document.querySelector('#section-suppliers');
    if (!section) return;
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
  }

  function simplifySales() {
    hide(document.querySelector('#section-ebay .sales-channel-panel'));
  }

  function keepCJOnly(select) {
    if (!select) return;
    [...select.options].forEach(option => {
      const text = String(option.textContent || '').toLowerCase();
      if (option.value && !text.includes('cj')) option.remove();
    });
  }

  function simplifyProducts() {
    const section = document.querySelector('#section-catalog');
    if (!section) return;
    section.querySelectorAll('button,a').forEach(node => {
      const text = String(node.textContent || '').toLowerCase();
      if (text.includes('ajouter un produit') || text.includes('importer csv') || text.includes('charger la démo')) hide(node);
    });
    hide(section.querySelector('#csvInput')?.closest('label'));

    const select = section.querySelector('#filterSupplier');
    if (select) {
      const normalize = () => {
        keepCJOnly(select);
        if ([...select.options].some(option => option.value)) select.options[0].textContent = 'CJ Dropshipping';
      };
      normalize();
      if (!supplierFilterObserver) {
        supplierFilterObserver = new MutationObserver(normalize);
        supplierFilterObserver.observe(select, { childList: true });
      }
    }
  }

  function lockSelect(select, value, label) {
    if (!select) return;
    if (![...select.options].some(option => option.value === value || option.textContent === value)) {
      select.add(new Option(label || value, value));
    }
    const option = [...select.options].find(row => row.value === value || row.textContent === value);
    if (option) option.value = value;
    select.value = value;
    select.disabled = true;
  }

  function simplifySettings() {
    const marketplace = document.querySelector('#marketplaceId');
    if (marketplace) {
      lockSelect(marketplace, 'EBAY_US', 'EBAY_US');
      marketplace.title = 'Le mode v0.23 est verrouillé sur eBay US';
    }
    const currency = document.querySelector('#currency');
    if (currency) {
      lockSelect(currency, 'USD', 'USD');
      currency.title = 'Le mode v0.23 utilise uniquement USD';
    }
    const riskForm = document.querySelector('#riskSettingsForm');
    const profit = riskForm?.elements?.min_profit_eur;
    if (profit?.closest('label')) profit.closest('label').childNodes[0].textContent = 'Profit minimum ($)';
    const fixed = riskForm?.elements?.fixed_fee;
    if (fixed?.closest('label')) fixed.closest('label').childNodes[0].textContent = 'Frais eBay par commande ($)';
  }

  function normalizeProductModal() {
    const modal = document.querySelector('#modalBody');
    if (!modal) return;
    const form = modal.querySelector('#productForm, form[data-id]');
    if (!form) return;

    modal.querySelectorAll('label').forEach(label => {
      const first = label.childNodes?.[0];
      if (!first || first.nodeType !== Node.TEXT_NODE) return;
      first.textContent = String(first.textContent || '')
        .replace('Coût fournisseur (€)', 'Coût fournisseur ($)')
        .replace('Livraison (€)', 'Livraison ($)')
        .replace('Prix eBay visé (€)', 'Prix eBay US visé ($)');
    });

    const marketplace = form.elements?.marketplace_id;
    if (marketplace) lockSelect(marketplace, 'EBAY_US', 'EBAY_US');
    const supplier = form.elements?.supplier_id;
    if (supplier) keepCJOnly(supplier);

    const hint = modal.querySelector('.info-box');
    if (hint && String(hint.textContent || '').includes('marketplace')) {
      hint.textContent = 'Mode verrouillé : eBay US · USD · CJ Dropshipping.';
    }
  }

  function watchModal() {
    const modal = document.querySelector('#modalBody');
    if (!modal || modalObserver) return;
    modalObserver = new MutationObserver(() => normalizeProductModal());
    modalObserver.observe(modal, { childList: true, subtree: true });
    normalizeProductModal();
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
    simplifyProducts();
    simplifySettings();
    watchModal();
    removePipelineRemnants();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, { once: true });
  else apply();
  setTimeout(apply, 400);
  setTimeout(apply, 1200);
})();
