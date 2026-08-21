(() => {
  'use strict';

  const DIRTY_KEY = 'opsbot:catalog-dirty';
  const nativeFetch = window.fetch.bind(window);

  function isDirty() {
    try { return sessionStorage.getItem(DIRTY_KEY) === '1'; }
    catch { return false; }
  }

  function markDirty() {
    try { sessionStorage.setItem(DIRTY_KEY, '1'); } catch {}
    refreshVisibleCounts();

    if (document.querySelector('#section-catalog.active')) {
      openFreshCatalog();
    }
  }

  function clearDirty() {
    try { sessionStorage.removeItem(DIRTY_KEY); } catch {}
  }

  async function refreshVisibleCounts() {
    try {
      const response = await nativeFetch('/api/products', {cache: 'no-store'});
      if (!response.ok) return;
      const products = await response.json();
      if (!Array.isArray(products)) return;
      const count = products.length;
      const nav = document.querySelector('#navProductCount');
      const stat = document.querySelector('#statProducts');
      const hint = document.querySelector('#statProductsHint');
      if (nav) nav.textContent = String(count);
      if (stat) stat.textContent = String(count);
      if (hint) hint.textContent = count ? `${count} référence${count > 1 ? 's' : ''}` : 'Catalogue vide';
    } catch {}
  }

  function openFreshCatalog() {
    clearDirty();
    try {
      const url = new URL(window.location.href);
      url.hash = 'catalog';
      history.replaceState(null, '', url.href);
    } catch {
      history.replaceState(null, '', '#catalog');
    }
    window.location.reload();
  }

  function requestTargetsSupplierAdd(input, init) {
    const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'POST') return false;
    try {
      const raw = input instanceof Request ? input.url : String(input || '');
      const url = new URL(raw, window.location.origin);
      return url.origin === window.location.origin && url.pathname === '/api/supplier-flow/add';
    } catch {
      return false;
    }
  }

  window.fetch = async function syncedFetch(input, init) {
    const tracksProductAdd = requestTargetsSupplierAdd(input, init);
    const response = await nativeFetch(input, init);
    if (tracksProductAdd && response.ok) markDirty();
    return response;
  };

  document.addEventListener('click', event => {
    if (!isDirty()) return;
    const target = event.target.closest('[data-section="catalog"], [data-go="catalog"]');
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    openFreshCatalog();
  }, true);

  window.addEventListener('hashchange', () => {
    if (isDirty() && window.location.hash === '#catalog') openFreshCatalog();
  });
})();
