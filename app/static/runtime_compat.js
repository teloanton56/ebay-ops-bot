(() => {
  'use strict';

  // The current UI intentionally hides/removes several legacy panels while the
  // original app.js still contains refresh/render hooks for them. Keep invisible
  // DOM targets available so background refreshes can never crash on null nodes.
  const legacyTargets = {
    supplierDirectoryNote: 'div',
    supplierDirectoryResults: 'div',
    supplierDirectoryCategory: 'select',
    supplierDirectoryCatalog: 'select',
    supplierDirectoryQuery: 'input',
    supplierKpis: 'div',
    supplierProviderGrid: 'div',
    factoryList: 'div',
    rfqFactory: 'select',
    rfqList: 'div',
    radarSources: 'div',
  };

  function createHiddenTarget(id, tagName) {
    if (document.getElementById(id)) return;
    const node = document.createElement(tagName || 'div');
    node.id = id;
    node.hidden = true;
    node.setAttribute('aria-hidden', 'true');
    node.dataset.runtimeCompat = '1';
    document.body.appendChild(node);
  }

  function ensureLegacyTargets() {
    Object.entries(legacyTargets).forEach(([id, tagName]) => createHiddenTarget(id, tagName));
  }

  // Run before app.js initializes and again whenever cleanup scripts remove a
  // legacy panel. MutationObserver keeps the guarantee true for later refreshes.
  ensureLegacyTargets();

  const observer = new MutationObserver(() => ensureLegacyTargets());
  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener('error', event => {
    const message = String(event?.error?.message || event?.message || '');
    if (/null is not an object|cannot set properties of null|cannot read properties of null/i.test(message)) {
      ensureLegacyTargets();
    }
  });
})();
