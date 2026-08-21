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

  function cleanObsoleteCopy() {
    const radarTip = document.querySelector('.radar-signal-panel .help-tip');
    if (radarTip) {
      radarTip.dataset.tip = 'TikTok et YouTube servent uniquement à confirmer une piste précise détectée par le Radar.';
    }

    const autoText = document.querySelector('.auto-radar-heading p');
    if (autoText) {
      autoText.textContent = 'eBay est la source principale. Le bot parcourt les catégories, mesure les candidats, puis utilise YouTube et TikTok uniquement comme confirmations ciblées.';
    }

    document.querySelectorAll('.help-card').forEach(card => {
      const title = (card.querySelector('h2')?.textContent || '').trim();
      const paragraph = card.querySelector('p');
      if (!paragraph) return;
      if (title.includes('Repérer puis confirmer')) {
        paragraph.textContent = 'Le Radar détecte et mesure les opportunités eBay. Amazon complète certains signaux catalogue ; YouTube et TikTok servent de confirmations ciblées. Aucun volume de recherche privé n’est inventé.';
      }
      if (title.includes('Trouver l’offre adaptée')) {
        paragraph.textContent = 'Compare CJ Dropshipping, Amazon et AliExpress, puis ajoute directement l’offre retenue aux Produits. Un fournisseur manuel ou un CSV reste disponible uniquement en secours.';
      }
      if (title.includes('Brancher les sources officielles')) {
        paragraph.textContent = 'Regroupe eBay, CJ Dropshipping, Amazon, AliExpress, YouTube et TikTok. Une connexion n’est considérée comme prête qu’après une vérification réelle auprès du service concerné.';
      }
    });
  }

  // Run before app.js initializes and again whenever cleanup scripts remove a
  // legacy panel. MutationObserver keeps the guarantee true for later refreshes.
  ensureLegacyTargets();

  const observer = new MutationObserver(() => {
    ensureLegacyTargets();
    cleanObsoleteCopy();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', cleanObsoleteCopy, { once: true });
  } else {
    cleanObsoleteCopy();
  }

  window.addEventListener('error', event => {
    const message = String(event?.error?.message || event?.message || '');
    if (/null is not an object|cannot set properties of null|cannot read properties of null/i.test(message)) {
      ensureLegacyTargets();
    }
  });
})();
