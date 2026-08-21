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

  function cleanup(root = document) {
    if (root instanceof Element && removeNodeIfLegacy(root)) return;

    removedProviders.forEach(provider => {
      root.querySelectorAll?.(`[data-provider-card="${provider}"]`).forEach(node => node.remove());
    });

    root.querySelectorAll?.(namedCardSelector).forEach(node => {
      if (hasRemovedName(node)) node.remove();
    });
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
