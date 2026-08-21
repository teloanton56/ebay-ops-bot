(() => {
  'use strict';

  const removedProviders = new Set(['printful', 'printify', 'gelato']);
  const removedNames = ['printful', 'printify', 'gelato'];

  function removeLegacyProviderCards(root = document) {
    removedProviders.forEach(provider => {
      root.querySelectorAll?.(`[data-provider-card="${provider}"]`).forEach(node => node.remove());
    });
  }

  function removeNamedProviderCards(root = document) {
    const selectors = ['.radar-source', '.provider-card', '.supplier-provider-card', '.directory-card', '.connection-card'];
    root.querySelectorAll?.(selectors.join(',')).forEach(node => {
      const text = (node.textContent || '').trim().toLowerCase();
      if (removedNames.some(name => text.includes(name))) node.remove();
    });
  }

  function cleanup(root = document) {
    removeLegacyProviderCards(root);
    removeNamedProviderCards(root);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => cleanup());
  } else {
    cleanup();
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
