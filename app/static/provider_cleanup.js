(() => {
  'use strict';

  const removedProviders = new Set(['printful', 'printify', 'gelato']);
  const removedNames = ['printful', 'printify', 'gelato'];
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

  function promoteMarketplaceSuppliers(root = document) {
    const amazon = root.querySelector?.('[data-provider-card="amazon"]');
    if (amazon) {
      const kicker = amazon.querySelector('.panel-kicker');
      const paragraph = amazon.querySelector(':scope > p');
      const note = amazon.querySelector('.policy-note');
      if (kicker) kicker.textContent = 'RADAR + FOURNISSEUR';
      if (paragraph) paragraph.textContent = 'Recherche catalogue et prix Amazon France, utilisables aussi dans le comparateur fournisseur.';
      if (note) note.textContent = 'Le comparateur utilise les données observées et exige la confirmation du stock et de la livraison avant validation de marge.';
    }

    const cards = [...(root.querySelectorAll?.('.connection-card') || [])];
    const aliexpress = cards.find(card => (card.querySelector('h2')?.textContent || '').trim().toLowerCase() === 'aliexpress');
    if (aliexpress) {
      aliexpress.classList.remove('policy-card');
      const kicker = aliexpress.querySelector('.panel-kicker');
      const badge = aliexpress.querySelector('.status-badge');
      const paragraph = aliexpress.querySelector(':scope > p');
      const note = aliexpress.querySelector('.policy-note');
      if (kicker) kicker.textContent = 'FOURNISSEUR MARKETPLACE';
      if (badge) {
        badge.textContent = 'Disponible au sourcing';
        badge.className = 'status-badge neutral';
      }
      if (paragraph) paragraph.textContent = 'AliExpress peut alimenter le sourcing et la comparaison de prix produits dans le Centre fournisseurs.';
      if (note) note.textContent = 'Les résultats sont classés avec les autres fournisseurs. Les frais de livraison et le stock sont confirmés avant calcul final de rentabilité.';
    }
  }

  function cleanup(root = document) {
    if (root instanceof Element && removeNodeIfLegacy(root)) return;

    removedProviders.forEach(provider => {
      root.querySelectorAll?.(`[data-provider-card="${provider}"]`).forEach(node => node.remove());
    });

    root.querySelectorAll?.(namedCardSelector).forEach(node => {
      if (hasRemovedName(node)) node.remove();
    });
    promoteMarketplaceSuppliers(root);
  }

  function runCleanup() {
    cleanup(document);
    requestAnimationFrame(() => cleanup(document));
    setTimeout(() => cleanup(document), 250);
    setTimeout(() => cleanup(document), 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runCleanup, { once: true });
  } else {
    runCleanup();
  }

  const observer = new MutationObserver(records => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) cleanup(node);
      }
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
