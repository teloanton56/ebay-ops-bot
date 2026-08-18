(() => {
  'use strict';

  const state = { summary: null, products: [], suppliers: [], supplierHub: null, supplierDirectory: [], supplierOffers: {}, opportunities: null, discoveries: [], listings: [], settings: null, risk: null, finance: null, connections: [], ebayConnected: false, cjConnected: false, radarSources: [], radarWatch: [], factories: [], rfqs: [], cjProducts: [], cjCandidates: [], cjPage: 0, cjTotal: 0, cjTotalPages: 0, cjLoading: false, supportCases: [], salesChannels: [] };
  let deferredInstallPrompt = null;
  const $ = (q, root=document) => root.querySelector(q);
  const $$ = (q, root=document) => [...root.querySelectorAll(q)];

  const pageMeta = {
    overview:['Vue d’ensemble','Pilotage du catalogue, des marges et d’eBay.'],
    radar:['Radar marché','Détection automatique et validation des tendances.'],
    suppliers:['Fournisseurs','Catalogues, partenaires, fabricants et RFQ.'],
    catalog:['Produits','Opportunités, catalogue, marges et analyse automatique.'],
    ebay:['Canaux de vente','Marketplaces, annonces et commandes.'],
    support:['SAV','Demandes clients, délais et brouillons de réponse.'],
    finance:['Finance','Chiffre d’affaires, résultat et objectifs.'],
    connections:['Connexions','eBay, tendances et fournisseurs officiels.'],
    help:['Aide','Guide complet des fonctions et règles de sécurité.'],
    settings:['Paramètres','Règles de marge, sécurité et diagnostic.']
  };

  function esc(value='') { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c])); }
  function money(v, cur='EUR') {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
    try { return new Intl.NumberFormat('fr-FR',{style:'currency',currency:cur,maximumFractionDigits:2}).format(Number(v)); }
    catch { return Number(v).toFixed(2)+' €'; }
  }
  function percent(v){ return (v===null || v===undefined || Number.isNaN(Number(v))) ? '—' : Number(v).toFixed(1)+' %'; }
  function safeUrl(value='') {
    try { const url=new URL(String(value), location.origin); return ['http:','https:'].includes(url.protocol)?url.href:''; }
    catch { return ''; }
  }
  function detailMessage(data, fallback='Une erreur est survenue') {
    if (!data) return fallback;
    if (typeof data.detail === 'string') return data.detail;
    if (data.detail?.message) return data.detail.message;
    if (data.message) return data.message;
    return fallback;
  }
  async function fetchJson(url, options={}) {
    let response;
    try { response = await fetch(url, options); }
    catch (e) { throw new Error('Le bot local ne répond pas. Vérifie que la fenêtre noire est toujours ouverte.'); }
    const text = await response.text();
    let data = {};
    if (text) {
      try { data = JSON.parse(text); }
      catch { data = {message:text}; }
    }
    if (response.status === 401 && location.pathname !== '/login') {
      location.assign('/login');
      throw new Error('Session expirée. Reconnexion en cours…');
    }
    if (!response.ok) throw new Error(detailMessage(data, `Erreur ${response.status}`));
    return data;
  }

  const standaloneApp = () => window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const iosDevice = () => /iphone|ipad|ipod/i.test(navigator.userAgent);

  async function installApplication(){
    if(standaloneApp()){toast("L'application est déjà installée sur cet appareil");return;}
    if(deferredInstallPrompt){
      deferredInstallPrompt.prompt();
      await deferredInstallPrompt.userChoice;
      deferredInstallPrompt=null;
      return;
    }
    const body=iosDevice()
      ? '<div class="info-box"><strong>Installation sur iPhone</strong><p>1. Ouvrez cette page dans <strong>Safari</strong>.<br>2. Touchez le bouton <strong>Partager</strong> en bas de l’écran.<br>3. Choisissez <strong>Sur l’écran d’accueil</strong>, puis Ajouter.</p></div>'
      : '<div class="info-box"><strong>Installation sur ordinateur</strong><p>Ouvrez le menu de votre navigateur puis choisissez « Installer Ops Bot » ou « Installer cette application ».</p></div>';
    modal("Installer l'application",body,'WINDOWS · MAC · IPHONE');
  }

  async function loadCloudStatus(){
    const data=await fetchJson('/api/cloud/status');
    const cloud=data.mode==='cloud';
    $('#cloudStatusBadge').textContent=cloud?'Cloud actif':'Mode local';
    $('#cloudStatusBadge').className=`status-badge ${cloud?'good':'neutral'}`;
    $('#cloudModeValue').textContent=cloud?'Synchronisé':'Cet appareil';
    $('#cloudModeHelp').textContent=cloud?'Même catalogue sur Windows, Mac et iPhone.':'Les données restent sur cet ordinateur.';
    $('#cloudUpdateValue').textContent=data.automatic_updates?'Automatiques':'Par nouveau ZIP';
    $('#cloudBackupValue').textContent=data.backup_enabled?'Quotidiennes':'Manuelles';
    $('#cloudBackupHelp').textContent=data.backup_enabled?`${data.backup_retention} sauvegardes conservées`:'Utilisez le bouton ci-dessous';
    if(standaloneApp()) $('#installAppButton').textContent='Application installée';
  }

  async function showBackups(){
    const data=await fetchJson('/api/cloud/backups');
    const items=data.items||[];
    const rows=items.length?items.map(item=>`<div class="backup-row"><div><strong>${esc(item.name)}</strong><span>${new Date(item.created_at).toLocaleString('fr-FR')} · ${Math.max(1,Math.round(item.size_bytes/1024))} Ko</span></div><a class="mini-btn" href="/api/cloud/backups/${encodeURIComponent(item.name)}">Télécharger</a></div>`).join(''):'<div class="empty-state compact"><strong>Aucune sauvegarde créée</strong><span>La première sera créée automatiquement ou avec le bouton prévu.</span></div>';
    modal('Sauvegardes de vos données',`<p>Les ${esc(data.retention)} sauvegardes les plus récentes sont conservées.</p><div class="backup-list">${rows}</div>`,'PROTECTION');
  }

  async function createCloudBackup(){
    const button=$('#createBackupButton');button.disabled=true;
    try{await fetchJson('/api/cloud/backups',{method:'POST'});toast('Sauvegarde créée');await loadCloudStatus();}
    finally{button.disabled=false;}
  }

  async function logoutCloud(){
    await fetchJson('/api/cloud/logout',{method:'POST'});
    location.assign('/login');
  }

  async function exportSafeDiagnostic(){
    const button=$('#exportDiagnostic');button.disabled=true;button.textContent='Préparation…';
    try{
      const response=await fetch('/api/ui/diagnostic-export');
      if(response.status===401){location.assign('/login');return;}
      if(!response.ok)throw new Error(`Erreur ${response.status}`);
      const disposition=response.headers.get('content-disposition')||'';
      const filename=disposition.match(/filename="?([^";]+)"?/i)?.[1]||'diagnostic-opsbot.txt';
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
      link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Diagnostic sécurisé téléchargé');
    }finally{button.disabled=false;button.textContent='↓ Exporter le diagnostic sécurisé';}
  }

  function toast(msg) {
    const el=$('#toast'); el.textContent=msg; el.classList.add('show');
    clearTimeout(window.__toastTimer); window.__toastTimer=setTimeout(()=>el.classList.remove('show'),2800);
  }
  function safely(promise, label='Action impossible') { promise.catch(e=>toast(`${label} : ${e.message}`)); }
  function modal(title, html, kicker='') {
    $('#modalTitle').textContent=title; $('#modalKicker').textContent=kicker; $('#modalBody').innerHTML=html;
    $('#modal').classList.add('open'); $('#modal').setAttribute('aria-hidden','false'); document.body.style.overflow='hidden';
  }
  function closeModal(){ $('#modal').classList.remove('open'); $('#modal').setAttribute('aria-hidden','true'); document.body.style.overflow=''; }
  function loading(text='Chargement…'){ return `<div class="loading"><span class="spinner"></span>${esc(text)}</div>`; }

  function navigate(name) {
    if (!pageMeta[name]) name='overview';
    $$('.page-section').forEach(s=>s.classList.toggle('active', s.id===`section-${name}`));
    $$('.nav-item').forEach(b=>b.classList.toggle('active', b.dataset.section===name));
    $('#pageTitle').textContent=pageMeta[name][0]; $('#pageSubtitle').textContent=pageMeta[name][1];
    $('.sidebar')?.classList.remove('open');
    if(name==='settings') loadSettings();
    if(name==='ebay') safely(Promise.all([loadListings(),loadOrders(),loadSalesChannels()]),'Canaux de vente indisponibles');
    if(name==='support') safely(loadSupport(),'SAV indisponible');
    if(name==='finance') loadFinance();
    if(name==='radar') loadRadar();
    if(name==='connections') safely(Promise.all([loadConnections(),loadSettings()]),'Connexions indisponibles');
    if(name==='suppliers') safely(Promise.all([loadSuppliers(),loadSupplierHub(),loadSupplierDirectory(),loadCjCatalog()]),'Fournisseurs indisponibles');
    if(name==='catalog') safely(Promise.all([loadAutomation(),loadOpportunities()]),'Produits indisponibles');
    history.replaceState(null,'',`#${name}`);
  }

  async function refreshSummary() {
    const s=await fetchJson('/api/ui/summary'); state.summary=s;
    state.ebayConnected=!!s.connected;updateConnectionCount();
    $('#statProducts').textContent=s.products; $('#navProductCount').textContent=s.products;
    $('#statProductsHint').textContent=s.products ? `${s.products} référence${s.products>1?'s':''}` : 'Catalogue vide';
    $('#statPass').textContent=s.risk_pass; $('#statRiskHint').textContent=`${s.risk_block} bloqué${s.risk_block>1?'s':''}`;
    $('#statListings').textContent=s.listings;
    $('#statEbay').textContent=s.connected ? 'Connecté' : 'Hors ligne'; $('#statMarketplace').textContent=s.marketplace;
    $('#envChip').textContent=s.environment.toUpperCase();
    $('#demoChip').textContent=s.demo_mode ? 'MODE DÉMO' : 'LIVE DATA';
    $('#safetyChip').textContent=(s.write_enabled||s.publish_enabled)?'ÉCRITURE ACTIVE':'DRY-RUN';
    const conn=$('#connectionChip'); conn.classList.toggle('connected',s.connected); conn.querySelector('span:last-child').textContent=s.connected?'eBay connecté':(s.credentials_configured?'eBay à autoriser':'eBay non configuré');
    renderChecklist(s.setup_steps);
  }

  function renderChecklist(steps=[]) {
    const done=steps.filter(x=>x.done).length;
    $('#setupProgress').textContent=`${done}/${steps.length}`; $('#setupBar').style.width=`${steps.length?done/steps.length*100:0}%`;
    $('#setupChecklist').innerHTML=steps.map(s=>`<div class="check-item ${s.done?'done':''}"><span class="check-mark">${s.done?'✓':'·'}</span><span>${esc(s.label)}</span></div>`).join('');
  }

  async function loadProducts() {
    state.products=await fetchJson('/api/products');
    renderProducts();
  }

  function renderProducts() {
    const body=$('#productTableBody'), empty=$('#catalogEmpty');
    const text=($('#filterText')?.value||'').toLowerCase(), supplier=$('#filterSupplier')?.value||'', status=$('#filterStatus')?.value||'';
    const score=Number($('#filterScore')?.value||0), margin=Number($('#filterMargin')?.value||-999);
    const rows=state.products.filter(p=>(!text||`${p.title} ${p.supplier_sku}`.toLowerCase().includes(text))&&(!supplier||String(p.supplier_id)===supplier)&&(!status||p.product_status===status)&&Number(p.product_score?.score||0)>=score&&Number(p.risk?.profit?.margin_percent||-999)>=margin);
    if(!state.products.length){ body.innerHTML=''; empty.style.display='grid'; return; }
    empty.style.display='none';
    body.innerHTML=rows.map(p=>{
      const pr=p.risk?.profit||{}; const pass=!!p.risk?.pass; const currency=p.currency||'EUR';
      const supplierName=state.suppliers.find(s=>s.id===p.supplier_id)?.name||'Non rattaché';
      return `<tr>
        <td><div class="product-cell"><strong>${esc(p.title)}</strong><span>${esc(p.supplier_sku)} · ${esc(p.marketplace_id||'EBAY_FR')}</span></div></td>
        <td>${esc(supplierName)}<div class="seller">${money(p.supplier_cost,currency)} + ${money(p.shipping_cost,currency)}</div></td>
        <td><strong>${money(p.suggested_price||p.target_price,currency)}</strong><div class="seller">Cible ${money(p.target_price,currency)}</div></td>
        <td><button class="score-pill score-button" data-score-detail="${p.id}">${Number(p.product_score?.score||0).toFixed(0)}/100</button><div class="seller">${p.opportunity_score==null?'Local · marché non mesuré':`Marché eBay ${Number(p.opportunity_score).toFixed(0)}/100`}</div></td>
        <td class="${Number(pr.margin_percent)>=15?'margin-good':'margin-bad'}">${percent(pr.margin_percent)}<div class="seller">${money(pr.estimated_profit,currency)}</div></td>
        <td><select class="status-select" data-status="${p.id}"><option ${p.product_status==='À tester'?'selected':''}>À tester</option><option ${p.product_status==='Winner'?'selected':''}>Winner</option><option ${p.product_status==='Rejeté'?'selected':''}>Rejeté</option></select><div class="seller">Risk ${pass?'PASS':'BLOCK'}</div></td>
        <td><div class="action-menu"><button class="mini-btn" data-suggest="${p.id}">Calculer le prix</button><button class="mini-btn" data-edit-product="${p.id}">Modifier</button><button class="mini-btn primary" data-prepare="${p.id}">Préparer eBay</button><button class="mini-btn danger" data-delete-product="${p.id}" title="Supprimer">×</button></div></td>
      </tr>`;
    }).join('');
    if(!rows.length) body.innerHTML='<tr><td colspan="7"><div class="empty-state compact"><strong>Aucun produit ne correspond aux filtres.</strong></div></td></tr>';
  }

  function showProductScore(id){
    const product=state.products.find(row=>row.id===Number(id));if(!product)return;
    const score=product.product_score||{},factors=score.factors||[];
    modal(`Score de ${product.title}`,`<div class="modal-metrics"><div class="modal-metric"><small>Score produit</small><strong>${Number(score.score||0)}/100</strong></div><div class="modal-metric"><small>Source</small><strong>Calcul local</strong></div><div class="modal-metric"><small>Demande eBay</small><strong>${product.opportunity_score==null?'Non mesurée':Number(product.opportunity_score).toFixed(0)+'/100'}</strong></div></div><div class="score-breakdown">${factors.map(f=>`<div><span><strong>${esc(f.label)}</strong><small>${esc(f.detail)}</small></span><b>${Number(f.earned).toFixed(0)}/${f.maximum}</b></div>`).join('')}</div><div class="info-box"><strong>Mis à jour automatiquement.</strong><p>${esc(score.meaning||'Le score reflète la préparation du produit, pas des ventes inventées.')}</p></div>`,'SCORE PRODUIT');
  }

  async function loadOpportunities(){
    state.opportunities=await fetchJson('/api/products/opportunities/inbox');renderOpportunities();
  }
  function renderOpportunities(){
    const area=$('#productOpportunityArea'),data=state.opportunities;if(!area||!data)return;
    const themes=(data.themes||[]).slice(0,6),candidates=(data.cj_candidates||[]).slice(0,5);
    if(!themes.length&&!candidates.length){area.className='empty-state compact';area.innerHTML='<strong>Aucune piste disponible</strong><span>Lancez une détection automatique ou sélectionnez un produit chez un fournisseur.</span>';return}
    area.className='opportunity-columns';
    const themeRows=themes.length?themes.map(t=>`<div class="opportunity-row"><div><strong>${esc(t.keyword)}</strong><span>${esc(t.category)} · ${t.mentions} apparition(s) · ${esc(t.country)}</span></div><button class="mini-btn primary" data-find-suppliers="${esc(t.keyword)}">Trouver les offres</button></div>`).join(''):'<div class="empty-state compact"><strong>Aucune niche détectée</strong></div>';
    const candidateRows=candidates.length?candidates.map(c=>{const ready=c.analysis?.landed_cost_eur!==undefined;return `<div class="opportunity-row"><div><strong>${esc(c.name)}</strong><span>CJ · ${ready?`coût livré ${money(c.analysis.landed_cost_eur)}`:'transport à analyser'}</span></div>${ready?`<button class="mini-btn primary" data-add-cj-product="${c.id}">Ajouter au catalogue</button>`:`<button class="mini-btn" data-go-cj-candidate="${c.id}">Analyser</button>`}</div>`}).join(''):'<div class="empty-state compact"><strong>Aucun produit fournisseur sélectionné</strong></div>';
    area.innerHTML=`<section class="opportunity-column"><h3>Niches détectées automatiquement</h3><div class="opportunity-list">${themeRows}</div></section><section class="opportunity-column"><h3>Produits fournisseurs à décider</h3><div class="opportunity-list">${candidateRows}</div></section><p class="opportunity-note">${esc(data.note)}</p>`;
  }
  async function addCjProduct(candidateId){
    try{const d=await fetchJson(`/api/cj/candidates/${candidateId}/add-product`,{method:'POST'});toast(d.message);await Promise.all([refreshAll(),loadSuppliers(),loadOpportunities()]);navigate('catalog')}
    catch(e){modal('Produit non ajouté',`<div class="error-box">${esc(e.message)}</div>`,'CJ')}
  }

  async function loadDemo() {
    $('#catalogMessage').textContent='Chargement de la démo…';
    try { const d=await fetchJson('/api/products/load-demo',{method:'POST'}); toast(`${d.imported} produits démo chargés`); await refreshAll(); navigate('catalog'); }
    catch(e){ modal('Impossible de charger la démo',`<div class="error-box">${esc(e.message)}</div>`,'ERREUR'); }
    finally { $('#catalogMessage').textContent=''; }
  }

  function productForm(p={}) {
    return `<form id="addProductForm" data-id="${p.id||''}" class="form-grid">
      <label>SKU fournisseur<input name="supplier_sku" required placeholder="SUP-001" value="${esc(p.supplier_sku||'')}" ${p.id?'readonly':''}></label>
      <label>Nom du produit<input name="title" required placeholder="Support téléphone voiture" value="${esc(p.title||'')}"></label>
      <label>Fournisseur<select name="supplier_id"><option value="">Non rattaché</option>${state.suppliers.map(s=>`<option value="${s.id}" ${s.id===p.supplier_id?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
      <label>Statut<select name="product_status"><option ${p.product_status==='À tester'?'selected':''}>À tester</option><option ${p.product_status==='Winner'?'selected':''}>Winner</option><option ${p.product_status==='Rejeté'?'selected':''}>Rejeté</option></select></label>
      <label>Coût fournisseur (€)<input name="supplier_cost" type="number" step="0.01" min="0" required value="${p.supplier_cost??''}"></label>
      <label>Livraison (€)<input name="shipping_cost" type="number" step="0.01" min="0" value="${p.shipping_cost??0}"></label>
      <label>Stock<input name="stock" type="number" min="0" value="${p.stock??10}"></label>
      <label>Délai (jours)<input name="shipping_days" type="number" min="0" value="${p.shipping_days??3}"></label>
      <label>Prix eBay visé (€)<input name="target_price" type="number" step="0.01" min="0.01" required value="${p.target_price??''}"></label>
      <label>Marketplace<select name="marketplace_id"><option>EBAY_FR</option><option>EBAY_DE</option><option>EBAY_GB</option><option>EBAY_US</option></select></label>
      <label class="full">Description<textarea name="description" rows="4" placeholder="Informations fournisseur utiles…">${esc(p.description||'')}</textarea></label>
      <div class="full modal-actions"><button type="button" class="btn btn-ghost" data-close-modal>Annuler</button><button class="btn btn-primary" type="submit">${p.id?'Enregistrer':'Ajouter le produit'}</button></div>
    </form>`;
  }
  function showAddProduct(p={}){ modal(p.id?'Modifier le produit':'Ajouter un produit',productForm(p),'CATALOGUE FOURNISSEUR'); }
  async function submitProduct(form){
    const fd=new FormData(form); const payload=Object.fromEntries(fd.entries());
    ['supplier_cost','shipping_cost','target_price'].forEach(k=>payload[k]=Number(payload[k]||0));
    ['stock','shipping_days'].forEach(k=>payload[k]=Number(payload[k]||0)); payload.supplier_id=payload.supplier_id?Number(payload.supplier_id):null; payload.currency=payload.marketplace_id==='EBAY_US'?'USD':payload.marketplace_id==='EBAY_GB'?'GBP':'EUR';
    const id=form.dataset.id, url=id?`/api/products/${id}`:'/api/products';
    try{ await fetchJson(url,{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); closeModal(); toast(id?'Produit modifié':'Produit ajouté'); await refreshAll(); navigate('catalog'); }
    catch(e){ modal('Produit non ajouté',`<div class="error-box">${esc(e.message)}</div>${productForm()}`,'ERREUR'); }
  }

  async function importCsv(file){
    if(!file)return; const fd=new FormData(); fd.append('file',file); $('#catalogMessage').textContent='Import du fichier…';
    try{ const d=await fetchJson('/api/products/import-csv',{method:'POST',body:fd});
      if(d.errors?.length) modal('Import terminé avec avertissements',`<div class="warn-box"><strong>${d.imported} produits importés.</strong><p>${d.errors.length} ligne(s) n’ont pas pu être lues.</p></div><div class="preview-block"><label>Premières erreurs</label><div>${d.errors.slice(0,8).map(x=>`Ligne ${x.line}: ${esc(x.error)}`).join('\n')}</div></div>`,'CSV');
      else toast(`${d.imported} produit(s) importé(s)`); await refreshAll();
    }catch(e){modal('Import CSV impossible',`<div class="error-box">${esc(e.message)}</div><p>Le bot accepte les fichiers séparés par virgules <strong>ou</strong> point-virgules.</p>`,'CSV');}
    finally{$('#catalogMessage').textContent=''; $('#csvInput').value='';}
  }

  async function downloadCsv(){
    try{ const r=await fetch('/sample_supplier.csv'); if(!r.ok)throw new Error('Le modèle CSV est introuvable.'); const blob=await r.blob(); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='modele_fournisseur_ebay.csv'; document.body.appendChild(a); a.click(); URL.revokeObjectURL(a.href); a.remove(); toast('Modèle CSV téléchargé'); }
    catch(e){modal('Téléchargement impossible',`<div class="error-box">${esc(e.message)}</div>`,'CSV');}
  }
  function csvHelp(){ modal('Importer un catalogue fournisseur',`<div class="info-box"><strong>Le plus simple : ouvrez le vrai fichier modèle avec Excel ou Google Sheets.</strong><p>Une ligne = un produit. Le bot accepte les CSV avec virgules, point-virgules ou tabulations.</p></div><div class="preview-block"><label>Colonnes indispensables</label><div><strong>supplier_sku</strong> — référence fournisseur\n<strong>title</strong> — nom produit\n<strong>supplier_cost</strong> — coût d’achat</div></div><div class="preview-block"><label>Colonnes utiles</label><div>shipping_cost · stock · shipping_days · target_price · marketplace_id · currency · images · aspects_json</div></div><div class="modal-actions"><a class="btn btn-primary" href="/sample_supplier.csv" download="modele_fournisseur_ebay.csv">Télécharger le fichier CSV</a></div>`,'CSV'); }

  async function loadSuppliers(){
    state.suppliers=await fetchJson('/api/suppliers');
    const select=$('#filterSupplier'); if(select) select.innerHTML='<option value="">Tous les fournisseurs</option>'+state.suppliers.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('');
    const area=$('#supplierArea'); if(!area)return;
    if(!state.suppliers.length){area.className='empty-state';area.innerHTML='<div class="empty-icon">♙</div><strong>Aucun fournisseur manuel</strong><span>Ajoutez un partenaire puis importez son catalogue CSV.</span><button class="btn btn-primary" data-action="add-supplier">Ajouter</button>';return;}
    area.className='table-wrap';area.innerHTML=`<table class="data-table"><thead><tr><th>Fournisseur</th><th>Contact</th><th>Catalogue</th><th>Produits</th><th></th></tr></thead><tbody>${state.suppliers.map(s=>`<tr><td><div class="product-cell"><strong>${esc(s.name)}</strong><span>${esc(s.country)} · ${esc(s.supplier_type||'MANUEL')}</span></div></td><td>${esc(s.contact_name||'—')}<div class="seller">${esc(s.email||s.website||'Coordonnées à compléter')}</div></td><td><span class="status-badge neutral">${esc(s.catalog_status||'À importer')}</span><div class="supplier-catalog-meta">${s.provider_code?`<span>${esc(s.provider_code.toUpperCase())}</span>`:''}${s.catalog_url?`<span class="catalog-link">Flux enregistré</span>`:'<span>CSV manuel</span>'}</div></td><td>${s.product_count}</td><td><div class="supplier-actions"><label class="mini-btn file-control">Importer CSV<input type="file" accept=".csv,text/csv" data-supplier-import="${s.id}"></label><button class="mini-btn" data-edit-supplier="${s.id}">Modifier</button><button class="mini-btn danger" data-delete-supplier="${s.id}">Supprimer</button></div></td></tr>`).join('')}</tbody></table>`;
  }

  async function loadSupplierHub(){
    const hub=await fetchJson('/api/suppliers/hub');state.supplierHub=hub;state.factories=hub.factories||[];state.rfqs=hub.rfqs||[];
    const m=hub.metrics||{};$('#supplierKpis').innerHTML=[['Catalogues connectés',m.connected_catalogs||0],['Partenaires enregistrés',m.registered_suppliers||0],['Contacts fabricants',m.factory_contacts||0],['Brouillons RFQ',m.rfq_drafts||0]].map(([label,value])=>`<article><small>${esc(label)}</small><strong>${value}</strong></article>`).join('');
    const grid=$('#supplierProviderGrid');grid.innerHTML=(hub.providers||[]).map(p=>`<article class="supplier-provider-card ${p.connected?'connected':''}"><div class="supplier-provider-top"><div><h3>${esc(p.name)}</h3><span class="provider-kind">${esc(p.kind)}</span></div><span class="provider-status">${esc(p.status)}</span></div><p>${esc(p.note)}</p><div class="provider-footer"><span>${p.available_in_products?'Disponible dans Produits':p.connected?'Connecté':'Accès à finaliser'}</span>${p.connected?'<button class="mini-btn primary" data-use-provider="'+esc(p.id)+'">Utiliser</button>':`<a class="mini-btn" href="${esc(safeUrl(p.url||p.docs_url))}" target="_blank" rel="noopener">En savoir plus ↗</a>`}</div></article>`).join('');
    renderFactories();renderRfqs();
  }

  async function loadSupplierDirectory(){
    const params=new URLSearchParams({q:$('#supplierDirectoryQuery')?.value||'',category:$('#supplierDirectoryCategory')?.value||'',catalog:$('#supplierDirectoryCatalog')?.value||''});
    const data=await fetchJson('/api/suppliers/directory?'+params);state.supplierDirectory=data.results||[];
    const category=$('#supplierDirectoryCategory');if(category&&!category.dataset.loaded){category.innerHTML='<option value="">Toutes les niches</option>'+data.categories.map(value=>`<option>${esc(value)}</option>`).join('');category.dataset.loaded='1'}
    $('#supplierDirectoryNote').textContent=data.note;renderSupplierDirectory();
  }
  function renderSupplierDirectory(){
    const area=$('#supplierDirectoryResults');if(!area)return;
    if(!state.supplierDirectory.length){area.innerHTML='<div class="empty-state compact"><strong>Aucune piste pour ces filtres</strong><span>Essayez une niche plus large ou « Tous les accès ».</span></div>';return}
    area.innerHTML=state.supplierDirectory.map(row=>`<article class="directory-card"><div class="directory-card-head"><div><strong>${esc(row.name)}</strong><span>${esc(row.region)} · ${esc(row.model)}</span></div><span class="directory-format ${esc(row.catalog_level)}">${esc(row.catalog)}</span></div><div class="directory-tags">${row.categories.map(value=>`<span>${esc(value)}</span>`).join('')}</div><p>${esc(row.note)}</p><div class="directory-actions"><a class="mini-btn" href="${esc(safeUrl(row.url))}" target="_blank" rel="noopener">Ouvrir le site ↗</a><button class="mini-btn primary" data-add-directory="${esc(row.id)}">Ajouter aux pistes</button></div></article>`).join('');
  }
  function addDirectorySupplier(id){
    const row=state.supplierDirectory.find(item=>item.id===id);if(!row)return;
    const region=String(row.region||''),country=region.includes('Chine')?'CN':region.includes('Royaume-Uni')?'GB':region.includes('Amérique du Nord')?'US':region.includes('Europe')?'EU':'XX';
    showSupplier({name:row.name,website:row.url,country,supplier_type:row.model.toLowerCase().includes('fabricant')||row.categories.includes('Fabricants')?'USINE':'MANUEL',catalog_status:'À importer',notes:`Piste issue de l'annuaire · ${row.catalog}. ${row.note}`});
  }

  async function loadAutomation(){
    try{
      const [status,history,alerts]=await Promise.all([fetchJson('/api/automation/status'),fetchJson('/api/automation/history'),fetchJson('/api/automation/alerts')]);
      $('#autoState').textContent=status.enabled?'Actif':'En pause'; $('#autoSchedule').textContent=status.enabled?`Toutes les ${status.interval_minutes} min`:'Analyse manuelle'; $('#autoMode').textContent=status.mode==='EBAY'?'eBay réel':'Catalogue';
      const last=history[0]; $('#autoWinners').textContent=last?.winners??0; $('#autoRejected').textContent=last?.rejected??0;
      const unread=alerts.filter(a=>!a.read).length; $('#navAlertCount').textContent=unread;
      const readButton=$('#readAlerts'); readButton.disabled=unread===0; readButton.textContent=unread?`Marquer comme lu (${unread})`:'✓ Tout est lu';
      const alertArea=$('#alertsArea');
      if(!alerts.length){alertArea.className='empty-state compact';alertArea.innerHTML='<strong>Aucune alerte</strong><span>Les changements importants apparaîtront ici.</span>'}else{alertArea.className='alert-list';alertArea.innerHTML=alerts.map(a=>`<div class="alert-item ${esc(a.level)} ${a.read?'':'unread'}"><span class="alert-dot"></span><div><strong>${esc(a.product_title||a.kind)}</strong><span>${esc(a.message)}</span></div><small>${new Date(a.created_at).toLocaleString('fr-FR')}</small></div>`).join('')}
      const hist=$('#analysisHistory');
      if(!history.length){hist.className='empty-state compact';hist.innerHTML='<strong>Aucune analyse</strong><span>Lancez le premier scan du catalogue.</span>'}else{hist.className='history-list';hist.innerHTML=history.map(r=>`<div class="history-item"><span class="history-badge">${esc(r.mode)}</span><div><strong>${r.products_analyzed}/${r.products_total} produits · ${r.winners} Winner(s)</strong><span>${new Date(r.started_at).toLocaleString('fr-FR')} · ${r.errors} erreur(s)</span></div><small>${esc(r.status)}</small></div>`).join('')}
    }catch(e){toast('Automatisation indisponible : '+e.message)}
  }
  async function loadCjCatalog(){
    try{
      const status=await fetchJson('/api/cj/settings');
      state.cjConnected=!!status.connected; updateConnectionCount();
      if(!status.connected){
        $('#cjResults').innerHTML='<div class="empty-state compact"><strong>CJ n’est pas encore connecté</strong><span>Ajoutez la clé API dans Connexions pour activer la recherche catalogue.</span><button class="btn btn-primary" data-go="connections">Connecter CJ</button></div>';
        $('#cjResultTitle').textContent='Connexion requise';
        await loadCjCandidates();
        return;
      }
      if(!$('#cjCountry').dataset.loaded){const [warehouses,categories]=await Promise.all([fetchJson('/api/cj/warehouses'),fetchJson('/api/cj/categories')]);$('#cjCountry').innerHTML='<option value="">Tous les entrepôts</option>'+warehouses.map(w=>`<option value="${esc(w.country_code)}">${esc(w.name)} (${esc(w.country_code)})</option>`).join('');$('#cjCategory').innerHTML='<option value="">Toutes les catégories</option>'+categories.map(c=>`<option value="${esc(c.id)}">${esc(c.path)}</option>`).join('');$('#cjCountry').dataset.loaded='1'}
      await loadCjCandidates();
    }catch(e){modal('Catalogue CJ indisponible',`<div class="error-box">${esc(e.message)}</div>`,'CJ')}
  }
  function renderCjProducts(){
    const results=$('#cjResults'),shown=state.cjProducts.length;
    $('#cjResultTitle').textContent=state.cjTotal?`${shown} produit(s) affiché(s) sur ${state.cjTotal}`:'Aucun produit trouvé';
    if(!shown){results.innerHTML='<div class="empty-state compact"><strong>Aucun produit ne correspond à ces filtres.</strong><p>Essayez « Tous les entrepôts » ou retirez le prix maximum.</p></div>';return}
    const cards=state.cjProducts.map(p=>{const image=safeUrl(p.image_url);return `<article class="cj-card">${image?`<img src="${esc(image)}" alt="" loading="lazy">`:'<div class="image-placeholder">CJ</div>'}<div class="cj-card-body"><h3>${esc(p.name)}</h3><div class="cj-price">À partir de $${Number(p.price_usd||0).toFixed(2)}</div><div class="cj-card-meta"><span>Stock ${p.stock}</span><span>${esc(p.delivery_cycle||'Délai inconnu')} j</span><span>${p.has_ce?'CE déclaré':'CE non indiqué'}</span><span>${p.listed_num} listings CJ</span></div><p class="seller">${esc(p.category_name||'Non classé')} · ${esc(p.sku)}</p><button class="btn btn-primary" data-select-cj="${esc(p.cj_pid)}">Ajouter à ma sélection</button></div></article>`}).join('');
    const more=state.cjPage<state.cjTotalPages&&shown<state.cjTotal?`<div class="cj-pagination"><span>${shown} sur ${state.cjTotal} produits</span><button class="btn btn-secondary" data-cj-more>Afficher 20 produits de plus</button></div>`:`<div class="cj-pagination"><span>Les ${shown} produits disponibles sont affichés.</span></div>`;
    results.innerHTML=cards+more;
  }
  async function searchCj(append=false){
    if(state.cjLoading)return;state.cjLoading=true;const results=$('#cjResults'),page=append?state.cjPage+1:1;
    if(append){const button=$('[data-cj-more]');if(button){button.disabled=true;button.textContent='Chargement…'}}else{results.innerHTML=loading('Recherche dans le catalogue CJ…')}
    const params=new URLSearchParams({q:$('#cjQuery').value.trim(),country_code:$('#cjCountry').value,category_id:$('#cjCategory').value,min_stock:$('#cjMinStock').value||'0',order_by:$('#cjOrder').value,size:'20',page:String(page)});if($('#cjMaxPrice').value)params.set('max_price',$('#cjMaxPrice').value);
    try{const d=await fetchJson('/api/cj/products?'+params),next=d.products||[];state.cjProducts=append?[...new Map([...state.cjProducts,...next].map(p=>[p.cj_pid,p])).values()]:next;state.cjPage=Number(d.page||page);state.cjTotal=Number(d.total||state.cjProducts.length);state.cjTotalPages=Number(d.total_pages||1);renderCjProducts()}catch(e){if(append){toast(e.message);renderCjProducts()}else{results.innerHTML=`<div class="error-box">${esc(e.message)}</div>`}}finally{state.cjLoading=false}
  }
  async function loadCjCandidates(){
    state.cjCandidates=await fetchJson('/api/cj/candidates');$('#navCjCount').textContent=state.cjCandidates.length;const area=$('#cjCandidates');
    if(!state.cjCandidates.length){area.className='empty-state compact';area.innerHTML='<strong>Aucun produit sélectionné</strong><span>Les produits choisis apparaîtront ici avant analyse.</span>';return}
    area.className='candidate-list';area.innerHTML=state.cjCandidates.map(p=>{const a=p.analysis||{},ready=a.landed_cost_eur!==undefined,flags=p.risk_flags||[],image=safeUrl(p.image_url);return `<div class="candidate-row">${image?`<img src="${esc(image)}" alt="">`:'<div class="candidate-image-placeholder">CJ</div>'}<div class="candidate-main"><strong>${esc(p.name)}</strong><span>Catalogue : $${Number(p.price_usd).toFixed(2)} · stock ${p.stock}</span>${flags.length?`<div class="risk-flags">${flags.map(f=>`<span class="risk-flag ${esc(f.level)}">⚠ ${esc(f.label)}</span>`).join('')}</div>`:''}${ready?`<div class="candidate-analysis"><div><small>Coût livré</small><strong>${money(a.landed_cost_eur)}</strong></div><div><small>Transport</small><strong>${money(a.shipping_cost_eur)}</strong></div><div><small>Prix suggéré</small><strong>${money(a.suggested_price_eur)}</strong></div><div><small>Profit estimé</small><strong>${money(a.estimated_profit_eur)}</strong></div><p>${esc(a.shipping?.name||'Transport CJ')} · ${esc(a.shipping?.delivery_days||'délai inconnu')} · variante ${esc(a.variant?.sku||'')}</p></div>`:'<div class="candidate-pending">Transport et marge non calculés</div>'}</div><div class="candidate-actions"><button class="mini-btn primary" data-open-cj-analysis="${p.id}">${ready?'Recalculer':'Analyser'}</button>${ready?`<button class="mini-btn success" data-add-cj-product="${p.id}">Vers Produits</button>`:''}<button class="mini-btn" title="Retirer" data-remove-cj="${p.id}">×</button></div></div>`}).join('')
  }
  async function openCjAnalysis(candidateId){
    const candidate=state.cjCandidates.find(x=>x.id===Number(candidateId));if(!candidate)return;modal('Analyse du produit',loading('Chargement des variantes CJ…'),'COÛT FRANCE');
    try{const d=await fetchJson(`/api/cj/products/${candidate.cj_pid}/details`),flags=d.risk_flags||[];if(!d.variants.length){throw new Error('CJ ne propose aucune variante pour ce produit')}
      const image=safeUrl(d.image_url);
      modal('Calculer le coût vers la France',`${flags.length?`<div class="warn-box"><strong>Points de vigilance détectés</strong><p>${flags.map(f=>esc(f.label)).join('<br>')}</p></div>`:'<div class="success-box"><strong>Aucun risque logistique évident détecté.</strong><p>Les documents et règles eBay restent à vérifier avant toute publication.</p></div>'}<div class="product-detail-line">${image?`<img src="${esc(image)}" alt="">`:'<div class="candidate-image-placeholder">CJ</div>'}<div><strong>${esc(d.name)}</strong><span>${d.variants.length} variante(s) · ${d.packing_weight_g||d.weight_g||'—'} g · ${esc((d.logistics_properties||[]).join(', ')||'propriété non indiquée')}</span></div></div><form id="cjAnalysisForm" data-candidate-id="${candidate.id}" class="form-grid"><label class="full">Variante<select id="cjVariantChoice">${d.variants.map(v=>`<option value="${esc(v.vid)}">${esc(v.name)} — $${Number(v.price_usd).toFixed(2)} — ${v.weight_g||'—'} g</option>`).join('')}</select></label><label>Destination<input value="France" disabled></label><label>Code postal (facultatif)<input id="cjDestinationPostcode" maxlength="12" placeholder="Ex. 75001"></label><div class="full info-box"><strong>Calcul réel CJ, mais sans commande.</strong><p>Le bot prendra le transport compatible le moins cher retourné par CJ et le taux USD/EUR de la BCE.</p></div><div class="full modal-actions"><button type="button" class="btn btn-ghost" data-close-modal>Annuler</button><button type="submit" class="btn btn-primary">Calculer transport et marge</button></div></form>`,'COÛT FRANCE')
    }catch(e){modal('Analyse CJ impossible',`<div class="error-box">${esc(e.message)}</div>`,'CJ')}
  }
  async function runCjCostAnalysis(form){
    const button=form.querySelector('button[type="submit"]');button.disabled=true;button.textContent='Calcul en cours…';
    try{const d=await fetchJson(`/api/cj/candidates/${form.dataset.candidateId}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vid:$('#cjVariantChoice').value,destination_country:'FR',postcode:$('#cjDestinationPostcode').value.trim()})});closeModal();toast('Transport et marge calculés');await loadCjCandidates();return d}catch(e){button.disabled=false;button.textContent='Réessayer';modal('Calcul impossible',`<div class="error-box">${esc(e.message)}</div>`,'CJ')}
  }
  async function selectCj(pid){const p=state.cjProducts.find(x=>x.cj_pid===pid);if(!p)return;try{await fetchJson('/api/cj/candidates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});toast('Produit ajouté à la sélection');await loadCjCandidates()}catch(e){toast(e.message)}}
  async function runAnalysis(){const b=$('#runAnalysis');b.disabled=true;b.textContent='Analyse en cours…';$('#autoState').textContent='Analyse…';try{const d=await fetchJson('/api/automation/analyze-now',{method:'POST'});if(d.already_running){toast(d.message)}else{modal('Analyse terminée',`<div class="success-box"><strong>${d.products_analyzed}/${d.products_total} produit(s) contrôlé(s)</strong><p>${d.winners} Winner(s) · ${d.rejected} rejeté(s) · ${d.errors} erreur(s).</p></div><div class="info-box"><strong>${d.market_data?'Données eBay Production utilisées':'Contrôle catalogue uniquement'}</strong><p>${d.market_data?'Le score marché provient des annonces eBay actives observées.':'Aucune demande marché n’a été inventée : seules les marges, le stock et les règles de sécurité ont été contrôlés.'}</p></div><p>Aucune donnée n’a été publiée sur eBay.</p>`,'DRY-RUN');await refreshAll();await loadAutomation()}}catch(e){modal('Analyse interrompue',`<div class="error-box">${esc(e.message)}</div>`,'AUTOMATISATION')}finally{b.disabled=false;b.textContent='✦ Analyser maintenant';$('#autoState').textContent='Prêt'}}
  function supplierForm(s={}){return `<form id="supplierForm" data-id="${s.id||''}" class="form-grid"><label>Nom du fournisseur<input name="name" required value="${esc(s.name||'')}"></label><label>Type<select name="supplier_type"><option value="MANUEL" ${s.supplier_type==='MANUEL'?'selected':''}>Grossiste / fournisseur</option><option value="USINE" ${s.supplier_type==='USINE'?'selected':''}>Fabricant / usine</option><option value="API" ${s.supplier_type==='API'?'selected':''}>Catalogue API</option></select></label><label>Contact<input name="contact_name" value="${esc(s.contact_name||'')}"></label><label>Email<input name="email" type="email" value="${esc(s.email||'')}"></label><label>Site web<input name="website" type="url" value="${esc(s.website||'')}"></label><label>Pays (2 lettres)<input name="country" maxlength="2" value="${esc(s.country||'FR')}"></label><label class="full">Adresse du catalogue ou flux CSV (facultatif)<input name="catalog_url" type="url" value="${esc(s.catalog_url||'')}" placeholder="https://fournisseur.example/catalogue.csv"></label><label>État du catalogue<select name="catalog_status"><option ${s.catalog_status==='À importer'?'selected':''}>À importer</option><option ${s.catalog_status==='Reçu'?'selected':''}>Reçu</option><option ${s.catalog_status==='Connecté'?'selected':''}>Connecté</option><option ${s.catalog_status==='À actualiser'?'selected':''}>À actualiser</option></select></label><label>Fiabilité /100 <span class="help-tip" tabindex="0" data-tip="À renseigner après des commandes réelles : délais, annulations, qualité et stabilité du prix.">?</span><input name="reliability_score" type="number" min="0" max="100" step="1" value="${s.reliability_score??''}" placeholder="Non évalué"></label><label class="full">Notes<textarea name="notes" placeholder="MOQ, délais, certifications, conditions…">${esc(s.notes||'')}</textarea></label><div class="full modal-actions"><button type="button" class="btn btn-ghost" data-close-modal>Annuler</button><button class="btn btn-primary">Enregistrer</button></div></form>`}
  function showSupplier(s={}){modal(s.id?'Modifier le fournisseur':'Ajouter un fournisseur',supplierForm(s),'SOURCING')}
  async function saveSupplier(form){const p=Object.fromEntries(new FormData(form).entries()),id=form.dataset.id;if(p.reliability_score==='')delete p.reliability_score;try{await fetchJson(id?`/api/suppliers/${id}`:'/api/suppliers',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});closeModal();toast('Fournisseur enregistré');await Promise.all([loadSuppliers(),loadProducts(),loadSupplierHub()])}catch(e){modal('Fournisseur non enregistré',`<div class="error-box">${esc(e.message)}</div>${supplierForm(p)}`,'FOURNISSEURS')}}
  async function importSupplier(file,id){if(!file)return;const fd=new FormData();fd.append('file',file);try{const d=await fetchJson(`/api/products/import-csv/${id}`,{method:'POST',body:fd});toast(`${d.imported} produit(s) importé(s)`);await refreshAll();await loadSuppliers()}catch(e){modal('Import impossible',`<div class="error-box">${esc(e.message)}</div>`,'CSV')}}
  async function changeStatus(id,status){try{await fetchJson(`/api/products/${id}/status`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});toast('Statut mis à jour');await loadProducts()}catch(e){toast('Statut non modifié : '+e.message);await loadProducts()}}
  async function suggestProduct(id){try{const d=await fetchJson(`/api/products/${id}/suggest-price`,{method:'POST'}),p=d.profit;modal('Prix automatique',`<div class="modal-metrics"><div class="modal-metric"><small>Prix suggéré</small><strong>${money(d.suggested_price)}</strong></div><div class="modal-metric"><small>Minimum viable</small><strong>${money(d.minimum_viable_price)}</strong></div><div class="modal-metric"><small>Profit</small><strong>${money(p.estimated_profit)}</strong></div><div class="modal-metric"><small>Marge</small><strong>${percent(p.margin_percent)}</strong></div></div><div class="preview-block"><label>Détail du calcul</label><div>Coût fournisseur : ${money(p.supplier_cost)}\nLivraison : ${money(p.shipping_cost)}\nFrais eBay : ${money(p.estimated_ebay_fee)}\nPublicité : ${money(p.estimated_ad_fee)}\nRéserve retours : ${money(p.returns_reserve)}\nFrais fixes : ${money(p.fixed_fee)}\nCoût total estimé : ${money(p.total_estimated_cost)}\nSeuil de rentabilité : ${money(p.break_even_price)}\nROI : ${percent(p.roi_percent)}</div></div>`,'MARGE');await loadProducts()}catch(e){toast(e.message)}}
  async function prepareProduct(id){try{const d=await fetchJson(`/api/products/${id}/prepare-ebay`,{method:'POST'});modal('Prêt pour eBay',`<div class="success-box"><strong>Brouillon local créé en Dry-run.</strong><p>${esc(d.message)}</p></div>`,'SÉCURITÉ');await refreshSummary();await loadListings()}catch(e){modal('Préparation bloquée',`<div class="error-box">${esc(e.message)}</div>`,'RISK ENGINE')}}

  async function generateListing(id){
    modal('Génération de fiche',loading('Préparation de la fiche…'),'LISTING');
    try{ const d=await fetchJson(`/api/products/${id}/generate-listing`,{method:'POST'}); const p=d.product, r=d.risk, profit=r?.profit||{};
      modal('Fiche eBay préparée',`<div class="${r.pass?'success-box':'warn-box'}"><strong>${r.pass?'Risk Engine : PASS':'Risk Engine : BLOCK'}</strong><p>${r.pass?'Le produit respecte les seuils actuels.':'La fiche peut être préparée, mais elle ne doit pas être publiée tant que les blocages restent présents.'}</p></div>
      <div class="modal-metrics"><div class="modal-metric"><small>Prix</small><strong>${money(p.target_price,p.currency)}</strong></div><div class="modal-metric"><small>Profit</small><strong>${money(profit.estimated_profit,p.currency)}</strong></div><div class="modal-metric"><small>Marge</small><strong>${percent(profit.margin_percent)}</strong></div><div class="modal-metric"><small>Stock</small><strong>${p.stock}</strong></div></div>
      <div class="preview-block"><label>Titre optimisé</label><div>${esc(p.title)}</div></div><div class="preview-block"><label>Description</label><div>${esc(p.description||'')}</div></div>
      ${(r.blocks||[]).length?`<div class="error-box"><strong>Blocages</strong><p>${r.blocks.map(esc).join('<br>')}</p></div>`:''}${(r.warnings||[]).length?`<div class="warn-box"><strong>À compléter</strong><p>${r.warnings.map(esc).join('<br>')}</p></div>`:''}`,'LISTING'); await refreshAll();
    }catch(e){modal('Génération impossible',`<div class="error-box">${esc(e.message)}</div>`,'LISTING');}
  }

  async function loadListings(){
    try{ state.listings=await fetchJson('/api/ui/listings'); const area=$('#listingArea');
      if(!state.listings.length){ area.className='empty-state'; area.innerHTML='<div class="empty-icon">◇</div><strong>Aucun listing suivi</strong><span>Les annonces préparées/publées seront affichées ici une fois les opérations Sandbox activées.</span><button class="btn btn-secondary" data-go="catalog">Ouvrir le catalogue</button>'; return; }
      area.className='table-wrap'; area.innerHTML=`<table class="data-table"><thead><tr><th>Produit</th><th>Statut</th><th>Prix</th><th>Quantité</th><th>Offer ID</th></tr></thead><tbody>${state.listings.map(l=>`<tr><td><div class="product-cell"><strong>${esc(l.product_title)}</strong><span>${esc(l.supplier_sku)}</span></div></td><td><span class="status-badge neutral">${esc(l.status)}</span></td><td>${money(l.last_price,l.currency||'EUR')}</td><td>${l.last_quantity??'—'}</td><td>${esc(l.offer_id||'—')}</td></tr>`).join('')}</tbody></table>`;
    }catch(e){ $('#listingArea').innerHTML=`<div class="error-box">${esc(e.message)}</div>`; }
  }

  async function loadOrders(){
    const area=$('#ordersArea'); area.className=''; area.innerHTML=loading('Vérification de la connexion eBay…');
    try{ const settings=await fetchJson('/api/settings/ebay');
      if(!settings.connected){ area.className='empty-state'; area.innerHTML=`<div class="empty-icon">▤</div><strong>${settings.configured?'Autorisation eBay requise':'Compte eBay non configuré'}</strong><span>${settings.configured?'Vos clés sont enregistrées. Il reste à autoriser le compte Sandbox.':'En attendant l’approbation Developer, vous pouvez continuer à travailler en mode démo.'}</span><button class="btn btn-primary" data-action="connect-ebay">${settings.configured?'Autoriser eBay':'Configurer eBay'}</button>`; return; }
      const d=await fetchJson('/api/ebay/orders'); const orders=d.orders||[];
      if(!orders.length){area.className='empty-state';area.innerHTML='<div class="empty-icon">▤</div><strong>Aucune commande</strong><span>Aucune commande n’a été trouvée sur le compte connecté.</span>';return;}
      area.className='table-wrap'; area.innerHTML=`<table class="data-table"><thead><tr><th>Commande</th><th>Date</th><th>Statut</th><th>Total</th></tr></thead><tbody>${orders.map(o=>`<tr><td>${esc(o.orderId||'—')}</td><td>${esc(o.creationDate||'—')}</td><td>${esc(o.orderFulfillmentStatus||'—')}</td><td>${money(o.pricingSummary?.total?.value,o.pricingSummary?.total?.currency||'EUR')}</td></tr>`).join('')}</tbody></table>`;
    }catch(e){area.className='';area.innerHTML=`<div class="error-box">${esc(e.message)}</div>`;}
  }

  async function loadSalesChannels(){
    const data=await fetchJson('/api/sales-channels');state.salesChannels=data.channels||[];
    const grid=$('#salesChannelGrid');if(!grid)return;
    grid.innerHTML=state.salesChannels.map(row=>`<article class="sales-channel-card ${row.priority===1?'recommended':''}"><div class="sales-channel-head"><div><strong>${esc(row.name)}</strong><span>${esc(row.region)}</span></div><em>${esc(row.status)}</em></div><h3>${esc(row.fit)}</h3><p>${esc(row.note)}</p><div><small>${esc(row.formats)}</small><a class="mini-btn" href="${esc(safeUrl(row.url))}" target="_blank" rel="noopener">Documentation ↗</a></div></article>`).join('');
    $('#salesChannelGuard').textContent=data.guardrail||'';
  }

  function supportCaseForm(row={}){
    const due=row.due_at?String(row.due_at).slice(0,16):'';
    return `<form id="supportCaseForm" data-id="${row.id||''}" class="form-grid"><label>Marketplace<select name="marketplace"><option value="EBAY" ${row.marketplace==='EBAY'?'selected':''}>eBay</option><option value="CDISCOUNT" ${row.marketplace==='CDISCOUNT'?'selected':''}>Cdiscount</option><option value="KAUFLAND" ${row.marketplace==='KAUFLAND'?'selected':''}>Kaufland</option><option value="AMAZON" ${row.marketplace==='AMAZON'?'selected':''}>Amazon</option><option value="TIKTOK_SHOP" ${row.marketplace==='TIKTOK_SHOP'?'selected':''}>TikTok Shop</option><option value="AUTRE" ${row.marketplace==='AUTRE'?'selected':''}>Autre</option></select></label><label>Référence commande<input name="order_ref" maxlength="100" value="${esc(row.order_ref||'')}" placeholder="Facultatif"></label><label>Alias client <span class="help-tip" tabindex="0" data-tip="Utilisez de préférence le pseudonyme marketplace, pas l'adresse ou le téléphone du client.">?</span><input name="buyer_alias" maxlength="100" value="${esc(row.buyer_alias||'')}"></label><label>Échéance de réponse<input name="due_at" type="datetime-local" value="${esc(due)}"></label><label class="full">Sujet<input name="subject" required maxlength="200" value="${esc(row.subject||'')}"></label><label>Motif<select name="category">${['Retard de livraison','Retour / remboursement','Produit endommagé','Produit non conforme','Adresse / commande','Autre'].map(value=>`<option ${row.category===value?'selected':''}>${value}</option>`).join('')}</select></label><label>Priorité<select name="priority">${['Normale','Haute','Urgente'].map(value=>`<option ${row.priority===value?'selected':''}>${value}</option>`).join('')}</select></label><label>Statut<select name="status">${['Nouveau','En cours','En attente client','Résolu'].map(value=>`<option ${row.status===value?'selected':''}>${value}</option>`).join('')}</select></label><label class="full">Message du client<textarea name="customer_message" rows="4">${esc(row.customer_message||'')}</textarea></label><label class="full">Notes internes<textarea name="internal_notes" rows="3">${esc(row.internal_notes||'')}</textarea></label><input type="hidden" name="draft_response" value="${esc(row.draft_response||'')}"><div class="full modal-actions"><button type="button" class="btn btn-ghost" data-close-modal>Annuler</button><button class="btn btn-primary">Enregistrer le dossier</button></div></form>`;
  }
  function showSupportCase(row={}){modal(row.id?'Modifier le dossier SAV':'Nouveau dossier SAV',supportCaseForm(row),'SAV')}
  async function saveSupportCase(form){
    const payload=Object.fromEntries(new FormData(form).entries()),id=form.dataset.id;if(!payload.due_at)payload.due_at=null;
    try{await fetchJson(id?`/api/support/cases/${id}`:'/api/support/cases',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});closeModal();toast('Dossier SAV enregistré');await loadSupport()}catch(e){modal('Dossier non enregistré',`<div class="error-box">${esc(e.message)}</div>${supportCaseForm(payload)}`,'SAV')}
  }
  async function loadSupport(){
    const data=await fetchJson('/api/support/cases');state.supportCases=data.cases||[];const m=data.metrics||{};$('#navSupportCount').textContent=m.open||0;
    $('#supportKpis').innerHTML=[['Dossiers ouverts',m.open||0],['Nouveaux',m.new||0],['Urgents',m.urgent||0],['En retard',m.overdue||0],['Résolus',m.resolved||0]].map(([label,value])=>`<article><small>${label}</small><strong>${value}</strong></article>`).join('');renderSupportCases();
  }
  function renderSupportCases(){
    const area=$('#supportCasesArea');if(!area)return;const query=($('#supportSearch')?.value||'').toLowerCase(),status=$('#supportStatusFilter')?.value||'',priority=$('#supportPriorityFilter')?.value||'';
    const rows=state.supportCases.filter(row=>(!query||`${row.subject} ${row.order_ref} ${row.buyer_alias} ${row.category}`.toLowerCase().includes(query))&&(!status||row.status===status)&&(!priority||row.priority===priority));
    if(!rows.length){area.className='empty-state';area.innerHTML=`<div class="empty-icon">♡</div><strong>${state.supportCases.length?'Aucun dossier ne correspond aux filtres':'Aucun dossier SAV'}</strong><span>Créez un dossier local ou attendez la connexion des commandes.</span>`;return}
    area.className='table-wrap';area.innerHTML=`<table class="data-table"><thead><tr><th>Dossier</th><th>Commande</th><th>Motif</th><th>Échéance</th><th>Priorité</th><th>Statut</th><th></th></tr></thead><tbody>${rows.map(row=>{const due=row.due_at?new Date(row.due_at):null,overdue=due&&due<new Date()&&row.status!=='Résolu';return `<tr><td><div class="product-cell"><strong>${esc(row.subject)}</strong><span>${esc(row.buyer_alias||'Client non renseigné')} · ${esc(row.marketplace)}</span></div></td><td>${esc(row.order_ref||'—')}</td><td>${esc(row.category)}</td><td class="${overdue?'support-overdue':''}">${due?due.toLocaleString('fr-FR'):'—'}</td><td><span class="status-badge ${row.priority==='Urgente'?'danger':row.priority==='Haute'?'review':'neutral'}">${esc(row.priority)}</span></td><td><select class="status-select" data-support-status="${row.id}">${['Nouveau','En cours','En attente client','Résolu'].map(value=>`<option ${row.status===value?'selected':''}>${value}</option>`).join('')}</select></td><td><div class="action-menu"><button class="mini-btn primary" data-draft-support="${row.id}">Préparer réponse</button><button class="mini-btn" data-edit-support="${row.id}">Modifier</button><button class="mini-btn danger" data-delete-support="${row.id}">×</button></div></td></tr>`}).join('')}</tbody></table>`;
  }
  async function draftSupportResponse(id){
    try{const data=await fetchJson(`/api/support/cases/${id}/draft-response`,{method:'POST'});modal('Brouillon de réponse',`<div class="info-box"><strong>Aucun envoi automatique.</strong><p>${esc(data.message)}</p></div><label class="draft-response-label">Texte à relire<textarea id="supportDraftText" rows="12">${esc(data.draft)}</textarea></label><div class="modal-actions"><button class="btn btn-ghost" data-close-modal>Fermer</button><button class="btn btn-primary" data-copy-support-draft>Copier le texte</button></div>`,'SAV');await loadSupport()}catch(e){toast('Brouillon impossible : '+e.message)}
  }

  function financeBuckets(series,maxBuckets=60){
    if(series.length<=maxBuckets)return series;const size=Math.ceil(series.length/maxBuckets),rows=[];
    for(let i=0;i<series.length;i+=size){const group=series.slice(i,i+size);rows.push({date:group[group.length-1].date,revenue:group.reduce((n,x)=>n+Number(x.revenue||0),0),net_result:group.reduce((n,x)=>n+Number(x.net_result||0),0),orders:group.reduce((n,x)=>n+Number(x.orders||0),0),days:group.length})}return rows
  }
  function renderFinanceChart(series){
    if(!series.some(x=>Number(x.revenue||0)!==0||Number(x.net_result||0)!==0)){$('#financeChart').innerHTML='<div class="empty-state compact"><strong>Aucune vente sur cette période</strong><span>Le graphique apparaîtra dès la première commande eBay.</span></div>';return}
    const rows=financeBuckets(series),max=Math.max(...rows.flatMap(x=>[Number(x.revenue||0),Math.max(Number(x.net_result||0),0)]),1);
    $('#financeChart').innerHTML=`<div class="finance-bars">${rows.map(x=>{const revenue=Math.max(Number(x.revenue||0),0),profit=Math.max(Number(x.net_result||0),0),label=new Date(x.date+'T12:00:00').toLocaleDateString('fr-FR',{day:'2-digit',month:'short'});return `<div class="finance-bar" title="${esc(label)} · CA ${money(revenue)} · résultat ${money(x.net_result)}"><div class="bar-columns"><i class="revenue" style="height:${Math.max(revenue/max*100,1)}%"></i><i class="profit" style="height:${Math.max(profit/max*100,1)}%"></i></div><span>${rows.length<=31?esc(label):''}</span></div>`}).join('')}</div>`
  }
  async function loadFinance(){
    const days=Math.min(Math.max(Number($('#financeDays').value||30),1),3650),target=Number($('#financeTarget').value||5000);$('#financeChart').innerHTML=loading('Actualisation des ventes…');
    try{const d=await fetchJson(`/api/finance/summary?days=${days}&target=${target}`);state.finance=d;const t=d.totals,g=d.goal,source=$('#financeSource');source.textContent=d.source==='EBAY'?'Ventes eBay actualisées':'Aucune vente';source.className=`status-badge ${d.source==='EBAY'?'good':'neutral'}`;
      $('#financeKpis').innerHTML=`<article><small>Chiffre d’affaires</small><strong>${money(t.revenue)}</strong><span>sur ${d.period_days} jours</span></article><article class="${t.net_result<0?'negative':''}"><small>Résultat net estimé</small><strong>${money(t.net_result)}</strong><span>hors fiscalité</span></article><article><small>Marge nette</small><strong>${percent(t.net_margin_percent)}</strong><span>estimation</span></article><article><small>Commandes</small><strong>${t.orders}</strong><span>sur la période</span></article><article><small>Panier moyen</small><strong>${money(t.average_order_value)}</strong><span>par commande</span></article>`;
      $('#financeGoalTitle').textContent=`Cap vers ${money(g.amount)}`;$('#financeGoalPercent').textContent=`${g.progress_percent.toFixed(1)} %`;$('#financeGoalBar').style.width=`${g.progress_percent}%`;
      $('#financeGoalStats').innerHTML=`<div><small>CA réalisé</small><strong>${money(t.revenue)}</strong></div><div><small>CA restant</small><strong>${money(g.remaining)}</strong></div><div><small>Période affichée</small><strong>${d.period_days} jours</strong></div><div><small>Ventes enregistrées</small><strong>${t.orders}</strong></div>`;
      $('#financeMilestones').innerHTML=d.milestones.map(m=>`<div class="milestone ${m.reached?'reached':''}"><span>${m.reached?'✓':'€'}</span><strong>${money(m.amount)}</strong><small>${m.reached?'Palier atteint':`${m.progress_percent.toFixed(0)} %`}</small></div>`).join('');
      renderFinanceChart(d.series||[]);const costLabels={supplier:'Produits fournisseurs',shipping:'Transport',ebay:'Frais eBay',ads:'Publicité',returns:'Réserve retours',fixed:'Frais fixes'};$('#financeCosts').innerHTML=Object.entries(d.costs).map(([key,value])=>{const share=t.revenue?Number(value)/t.revenue*100:0;return `<div class="cost-row"><div><span>${esc(costLabels[key]||key)}</span><strong>${money(value)}</strong></div><div class="cost-bar"><span style="width:${Math.min(share,100)}%"></span></div><small>${share.toFixed(1)} % du CA</small></div>`}).join('');
      const completeness=d.completeness?.cost_completeness_percent??100;$('#financeNotice').innerHTML=`<strong>${d.source==='EBAY'?'Ventes eBay récupérées à l’instant.':'Aucune commande eBay récupérée.'}</strong><p>${d.source==='EBAY'?`${esc(d.disclaimer)} Correspondance des coûts catalogue : ${completeness.toFixed(1)} %.`:'Le chiffre d’affaires et le résultat restent à 0 €. Aucune prévision ni vente fictive n’est ajoutée.'}</p>`
    }catch(e){$('#financeChart').innerHTML=`<div class="error-box">${esc(e.message)}</div>`}
  }

  async function loadRadar(){
    const requests=await Promise.allSettled([fetchJson('/api/radar/sources'),fetchJson('/api/radar/watchlist'),fetchJson('/api/radar/discoveries')]);
    const [sources,watch,discoveries]=requests;
    if(sources.status==='fulfilled'){state.radarSources=sources.value;renderRadarSources()}else{const area=$('#radarSources');if(area){area.className='empty-state compact';area.innerHTML=`<strong>Sources momentanément indisponibles</strong><span>${esc(sources.reason?.message||'Rechargez la page.')}</span>`}}
    if(watch.status==='fulfilled'){state.radarWatch=watch.value;renderRadarWatch()}
    if(discoveries.status==='fulfilled'){state.discoveries=discoveries.value;renderAutoDiscoveries()}
    const failures=requests.filter(x=>x.status==='rejected');if(failures.length)toast(`${failures.length} bloc(s) du Radar indisponible(s)`)
  }
  function renderRadarSources(){const area=$('#radarSources');area.innerHTML=state.radarSources.map(s=>`<div class="radar-source ${s.ready?'ready':''}"><span class="source-dot"></span><div><strong>${esc(s.name)}</strong><small>${esc(s.kind)}</small><p>${esc(s.note)}</p></div><em>${esc(s.status)}</em></div>`).join('')}
  function renderAutoDiscoveries(){
    const area=$('#autoTrendResults');if(!area)return;const latest=state.discoveries[0];
    if(!latest){area.className='empty-state compact';area.innerHTML='<strong>Aucun relevé e-commerce</strong><span>Connectez YouTube puis lancez l’analyse des Shorts.</span>';return}
    const themes=(latest.themes||[]).slice(0,12),items=(latest.items||[]).slice(0,8),isCommerce=latest.source==='YOUTUBE_SHORTS_COMMERCE',searched=latest.searched_count??items.length;
    const seeds=(latest.seed_hashtags||['#ecommerce','#dropshipping','#amazonfinds','#tiktokmademebuyit','#productfinds']).map(tag=>`<span>${esc(tag)}</span>`).join('');
    const themeArea=themes.length?`<div class="trend-cloud">${themes.map(t=>`<button class="trend-chip" data-trend-keyword="${esc(t.keyword)}"><strong>${esc(t.keyword)}</strong><span>${esc(t.category)} · ${t.mentions} apparition(s)</span><span class="trend-score">${t.signal_score}/100 signal</span></button>`).join('')}</div>`:'<div class="empty-state compact"><strong>Aucun produit assez récurrent</strong><span>Les Shorts retenus restent visibles ci-dessous, mais le bot ne fabrique pas de tendance.</span></div>';
    const shortArea=items.length?`<div class="commerce-short-grid">${items.map(item=>{const url=safeUrl(item.url),image=safeUrl(item.image_url),views=new Intl.NumberFormat('fr-FR').format(Number(item.views||0)),tags=(item.hashtags||[]).slice(0,3).join(' '),tag=url?'a':'div';return `<${tag}${url?` href="${esc(url)}" target="_blank" rel="noopener noreferrer"`:''}>${image?`<img src="${esc(image)}" alt="">`:''}<span><strong>${esc(item.title||'Short YouTube')}</strong><small>${views} vues${item.duration_seconds?` · ${item.duration_seconds} s`:''}</small><em>${esc(tags||item.channel||'Short e-commerce')}</em></span></${tag}>`}).join('')}</div>`:'';
    area.className='commerce-discovery';area.innerHTML=`<div class="trend-summary"><div><strong>${themes.length} piste(s) produit · ${items.length} Short(s) affiché(s)</strong><span>${new Date(latest.scanned_at).toLocaleString('fr-FR')} · ${searched} résultat(s) examiné(s) · ${esc(latest.country)}</span></div><button class="mini-btn" data-go="connections">Source YouTube</button></div>${isCommerce?`<div class="commerce-seeds"><small>Veille ciblée</small>${seeds}</div>`:'<div class="warn-box"><strong>Ancien relevé généraliste</strong><p>Lancez une nouvelle analyse pour le remplacer par les Shorts e-commerce.</p></div>'}${themeArea}${shortArea}<div class="discovery-guard">Les vues Shorts comptent les démarrages et relectures, pas des ventes. Une piste doit encore être confirmée sur eBay/Amazon, puis par le coût livré et la conformité fournisseur.</div>`;
  }
  async function runAutoDiscovery(){const button=$('#runAutoDiscovery'),area=$('#autoTrendResults');button.disabled=true;button.textContent='Analyse en cours…';area.className='';area.innerHTML=loading('Recherche des Shorts e-commerce récents et filtrage des produits…');try{const d=await fetchJson('/api/radar/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({country:$('#autoTrendCountry').value})});state.discoveries=[d,...state.discoveries];renderAutoDiscoveries();toast(`${d.themes.length} piste(s) produit détectée(s)`);await loadOpportunities()}catch(e){area.innerHTML=`<div class="error-box">${esc(e.message)}</div>`}finally{button.disabled=false;button.textContent='✦ Analyser les Shorts'}}
  function renderRadarWatch(){const area=$('#radarWatchlist');$('#navRadarCount').textContent=state.radarWatch.length;if(!state.radarWatch.length){area.className='empty-state compact';area.innerHTML='<strong>Aucun produit surveillé</strong><span>Ajoutez un mot-clé pour constituer votre liste de relevés.</span>';return}area.className='radar-watch-list';area.innerHTML=state.radarWatch.map(x=>`<div><span><strong>${esc(x.keyword)}</strong><small>${esc(x.notes||'Relevé automatique toutes les 6 h')}</small></span><button class="mini-btn primary" data-signal-watch="${esc(x.keyword)}">Réseaux</button><button class="mini-btn" data-scan-watch="${esc(x.keyword)}">Marketplaces</button><button class="mini-btn" data-delete-watch="${x.id}">×</button></div>`).join('')}
  async function saveRadarWatch(keyword,notes=''){if(!keyword.trim()){toast('Indiquez un produit à surveiller');return false}try{await fetchJson('/api/radar/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keyword:keyword.trim(),notes:notes.trim()})});toast('Produit ajouté à la surveillance');state.radarWatch=await fetchJson('/api/radar/watchlist');renderRadarWatch();return true}catch(e){toast(e.message);return false}}
  function radarMarketCard(m){
    const amazon=m.source==='AMAZON',history=m.history_available?(m.listing_change_percent===null?'Historique disponible':`${m.listing_change_percent>=0?'+':''}${m.listing_change_percent} % de résultats`):'Premier relevé';
    const metrics=amazon
      ?[['Résultats catalogue',new Intl.NumberFormat('fr-FR').format(m.total_results||0)],['Prix médian',m.pricing_available&&m.median_price!==null?money(m.median_price,m.currency||'EUR'):'Rôle Pricing requis'],['Offres observées',m.pricing_available?new Intl.NumberFormat('fr-FR').format(m.offers_sample||0):'Non fourni'],['Meilleur rang',m.best_sales_rank?`#${new Intl.NumberFormat('fr-FR').format(m.best_sales_rank)}`:'Non fourni']]
      :[['Annonces',new Intl.NumberFormat('fr-FR').format(m.total_results||0)],['Prix médian',money(m.median_price,m.currency||'EUR')],['Vendeurs observés',new Intl.NumberFormat('fr-FR').format(m.sellers_sample||0)],['Top vendeur',m.top_seller||'—']];
    const products=amazon&&m.items?.length?`<div class="amazon-radar-items">${m.items.map(item=>{const url=safeUrl(item.url),image=safeUrl(item.image_url),tag=url?'a':'div';return `<${tag}${url?` href="${esc(url)}" target="_blank" rel="noopener noreferrer"`:''}>${image?`<img src="${esc(image)}" alt="">`:''}<span><strong>${esc(item.title||item.asin)}</strong><small>${esc(item.category||'Amazon')}${item.sales_rank?` · rang #${new Intl.NumberFormat('fr-FR').format(item.sales_rank)}`:''}${item.price!==null&&item.price!==undefined?` · ${money(item.price,item.currency||m.currency)}`:''}</small></span></${tag}>`}).join('')}</div>`:'';
    const note=amazon?'Résultats estimés par Amazon · Volume exact de recherches et conversion concurrente non publics':'Recherche exacte et conversion concurrente non publiques';
    return `<article class="${amazon?'amazon-market-result':''}"><div class="radar-market-head"><strong>${esc(m.marketplace_name)}</strong><span>${esc(history)}</span></div><div class="radar-market-metrics">${metrics.map(([label,value])=>`<div><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join('')}</div><p>${note}</p>${products}</article>`;
  }
  async function runRadarScan(){
    const query=$('#radarQuery').value.trim(),markets=$$('input[name="radar_market"]:checked').map(x=>x.value),amazonMarkets=$$('input[name="amazon_market"]:checked').map(x=>x.value),area=$('#radarResults');
    if(!query||(!markets.length&&!amazonMarkets.length)){toast('Indiquez un produit et au moins un marché');return}
    area.className='';area.innerHTML=loading('Relevé des marketplaces…');
    try{
      const d=await fetchJson('/api/radar/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keyword:query,marketplaces:markets,amazon_marketplaces:amazonMarkets})});
      const warnings=d.errors?.length?`<div class="warn-box"><strong>${d.errors.length} source(s) non relevée(s)</strong><p>${d.errors.map(x=>`${esc(x.marketplace)} : ${esc(x.message)}`).join('<br>')}</p></div>`:'';
      area.innerHTML=`<div class="info-box"><strong>Données officielles mesurées uniquement.</strong><p>${esc(d.note)}</p></div>${warnings}<div class="radar-market-results">${d.markets.map(radarMarketCard).join('')}</div>`;
    }catch(e){area.innerHTML=`<div class="error-box">${esc(e.message)}</div>`}
  }
  function signalMetric(metric){if(metric.format==='money')return money(metric.value,metric.currency||'EUR');return Number.isFinite(Number(metric.value))?new Intl.NumberFormat('fr-FR').format(Number(metric.value)):esc(metric.value??'—')}
  async function runSignalScan(){
    const query=$('#radarSignalQuery').value.trim(),sources=$$('input[name="radar_source"]:checked').map(x=>x.value),country=$('#radarSignalCountry').value,area=$('#radarSignalResults');
    if(!query||!sources.length){toast('Indiquez un produit et au moins une source');return}
    area.className='';area.innerHTML=loading('Lecture des sources officielles…');
    try{
      const d=await fetchJson('/api/connections/signals/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keyword:query,sources,country})});
      const resultCards=d.results.map(r=>`<article class="signal-source-result"><div class="radar-market-head"><strong>${esc(r.source_name)}</strong><span>${r.observed_count} résultat(s) affiché(s)</span></div><div class="radar-market-metrics">${r.metrics.map(m=>`<div><small>${esc(m.label)}</small><strong>${signalMetric(m)}</strong></div>`).join('')}</div><p>${esc(r.note)}</p><div class="signal-items">${(r.items||[]).slice(0,6).map(item=>{const url=safeUrl(item.url),image=safeUrl(item.image_url),tag=url?'a':'div';return `<${tag}${url?` href="${esc(url)}" target="_blank" rel="noopener noreferrer"`:''}>${image?`<img src="${esc(image)}" alt="">`:''}<span><strong>${esc(item.title)}</strong><small>${esc(item.subtitle||'')} · ${esc(item.metric||'')}</small></span></${tag}>`}).join('')}</div></article>`).join('');
      area.innerHTML=`${d.errors?.length?`<div class="warn-box"><strong>${d.errors.length} source(s) indisponible(s)</strong><p>${d.errors.map(x=>`${esc(x.source)} : ${esc(x.message)}`).join('<br>')}</p></div>`:''}<div class="signal-results">${resultCards}</div>`;
    }catch(e){area.innerHTML=`<div class="error-box">${esc(e.message)}</div>`}
  }
  async function matchSuppliers(){
    const q=$('#supplierMatchQuery').value.trim(),area=$('#supplierMatchResults');if(!q)return;
    area.className='';area.innerHTML=loading('Recherche chez les fournisseurs connectés…');
    try{
      const d=await fetchJson('/api/radar/supplier-match?q='+encodeURIComponent(q));state.cjProducts=(d.groups.find(g=>g.source==='CJ')?.products)||[];
      state.supplierOffers={};let offerIndex=0;
      const groups=d.groups.map(g=>`<section class="supplier-result-group"><div class="radar-market-head"><strong>${esc(g.source)}</strong><span>${g.products.length} offre(s)</span></div><p>${esc(g.note)}</p><div class="radar-supplier-grid">${g.products.map(p=>{const provider=String(p.provider||g.source),isCj=provider.toUpperCase()==='CJ',numericPrice=isCj?p.price_usd:p.price,price=numericPrice===null||numericPrice===undefined?'Prix à vérifier':money(numericPrice,isCj?'USD':p.currency||'EUR'),image=safeUrl(p.image_url),offerId=`offer-${offerIndex++}`;state.supplierOffers[offerId]={provider:provider.toLowerCase(),supplier_sku:p.supplier_sku||p.sku||offerId,name:p.name,price:Number(numericPrice||0),currency:isCj?'USD':p.currency||'EUR',stock:p.stock,image_url:p.image_url||''};return `<article>${image?`<img src="${esc(image)}" alt="">`:''}<div><strong>${esc(p.name)}</strong><span>${price}${p.stock!==null&&p.stock!==undefined?` · stock ${p.stock}`:''}</span><small>${(p.quality_evidence||[]).map(esc).join(' · ')}</small>${isCj?`<button class="mini-btn primary" data-select-cj="${esc(p.cj_pid)}">Sélectionner chez CJ</button>`:numericPrice!==null&&numericPrice!==undefined?`<button class="mini-btn primary" data-add-supplier-offer="${offerId}">Ajouter aux Produits</button>`:'<span class="candidate-pending">Prix à configurer avant ajout</span>'}</div></article>`}).join('')}</div></section>`).join('');
      area.innerHTML=`<div class="info-box"><strong>${d.groups.length} fournisseur(s) interrogé(s)</strong><p>${esc(d.note)}</p></div>${groups}`;
    }catch(e){area.innerHTML=`<div class="error-box">${esc(e.message)}</div>`}
  }
  async function addSupplierOffer(offerId){const offer=state.supplierOffers[offerId];if(!offer)return;try{const d=await fetchJson('/api/products/from-supplier-offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(offer)});toast(d.message);await Promise.all([refreshAll(),loadSuppliers(),loadOpportunities()])}catch(e){modal('Offre non ajoutée',`<div class="error-box">${esc(e.message)}</div>`,'FOURNISSEUR')}}
  function renderFactories(){const area=$('#factoryList'),select=$('#rfqFactory');select.innerHTML='<option value="">Sans destinataire</option>'+state.factories.map(f=>`<option value="${f.id}">${esc(f.company)}</option>`).join('');if(!state.factories.length){area.className='empty-state compact';area.innerHTML='<strong>Aucun contact fabricant</strong><span>Préparez une recherche, vérifiez la fiche puis enregistrez le contact.</span>';return}area.className='factory-list';area.innerHTML=state.factories.map(f=>`<div><div><strong>${esc(f.company)}</strong><span>${esc(f.source||'Source non indiquée')} · ${esc(f.country||'pays inconnu')}</span><small>${esc(f.email||f.website||'Coordonnées à compléter')}</small></div><button class="mini-btn danger" title="Supprimer le contact" data-delete-factory="${f.id}">×</button></div>`).join('')}
  function renderRfqs(){const area=$('#rfqList');if(!state.rfqs.length){area.className='empty-state compact';area.innerHTML='<strong>Aucun devis préparé</strong><span>Rien ne sera envoyé automatiquement.</span>';return}area.className='rfq-list';area.innerHTML=state.rfqs.map(r=>`<div><span><strong>${esc(r.product_query)}</strong><small>${esc(r.factory_company||'Sans destinataire')} · ${esc(r.status)}</small></span><div class="rfq-actions"><button class="mini-btn" data-view-rfq="${r.id}">Voir</button><button class="mini-btn danger" data-delete-rfq="${r.id}" title="Supprimer le brouillon">×</button></div></div>`).join('')}
  async function discoverFactories(){const q=$('#factoryDiscoveryQuery').value.trim(),area=$('#factoryDiscoveryResults');area.className='';area.innerHTML=loading('Préparation des recherches fabricants…');try{const d=await fetchJson('/api/suppliers/factory-discovery',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})});$('#factoryDiscoveryQuery').value=d.query;area.innerHTML=`<div class="trend-summary"><div><strong>Recherche préparée : ${esc(d.query)}</strong><span>${d.origin==='trend'?'Issue automatiquement du dernier Radar':'Sujet indiqué manuellement'}</span></div><button class="mini-btn" data-prefill-rfq="${esc(d.query)}">Préparer un RFQ</button></div><div class="factory-directory-results">${d.directories.map(x=>`<a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener"><strong>${esc(x.name)} ↗</strong><span>${esc(x.strength)}</span></a>`).join('')}</div><div class="discovery-guard">${esc(d.automatic_limits)} ${esc(d.next_step)}</div>`}catch(e){area.innerHTML=`<div class="error-box">${esc(e.message)}</div>`}}
  async function saveFactory(form){const payload=Object.fromEntries(new FormData(form).entries());try{await fetchJson('/api/radar/factories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});form.reset();toast('Contact fabricant enregistré dans votre espace');await loadSupplierHub()}catch(e){toast(e.message)}}
  async function createRfq(form){const payload=Object.fromEntries(new FormData(form).entries());payload.factory_id=payload.factory_id?Number(payload.factory_id):null;try{const d=await fetchJson('/api/radar/rfqs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});modal('Brouillon de demande de prix',`<div class="success-box"><strong>Brouillon créé dans votre espace.</strong><p>Aucun message n’a été envoyé.</p></div><div class="preview-block"><label>Message en anglais</label><div>${esc(d.message)}</div></div>`,'RFQ');form.reset();await loadSupplierHub()}catch(e){toast(e.message)}}

  async function loadConnections(){
    try{const d=await fetchJson('/api/connections');state.connections=d.sources||[];renderConnections()}
    catch(e){$$('.connection-form').forEach(form=>{const help=$(`#connectionHelp-${form.dataset.provider}`);if(help)help.innerHTML=`<span>Connexion momentanément indisponible : ${esc(e.message)}</span>`});toast('Connexions indisponibles : '+e.message)}
  }
  function updateConnectionCount(){
    const count=state.connections.filter(x=>x.connected).length+(state.cjConnected?1:0)+(state.ebayConnected?1:0);
    $('#navConnectionCount').textContent=count;
  }
  function renderConnections(){
    updateConnectionCount();
    state.connections.forEach(c=>{const badge=$(`#connectionStatus-${c.id}`),form=$(`.connection-form[data-provider="${c.id}"]`),help=$(`#connectionHelp-${c.id}`);if(!badge||!form)return;badge.textContent=c.status;badge.className=`status-badge ${c.connected?'good':'neutral'}`;form.querySelectorAll('input[type="password"]').forEach(input=>{input.placeholder=c.configured?`${c.credential_masked} — laisser vide pour conserver`:'Identifiant fourni par la plateforme'});if(form.elements.api_email)form.elements.api_email.placeholder=c.configured?'Email du compte conservé':'Email du compte DropXL';if(form.elements.environment)form.elements.environment.value=c.environment||'production';help.innerHTML=`<span>${c.connected?`Vérifiée ${new Date(c.verified_at).toLocaleString('fr-FR')}`:c.last_error?esc(c.last_error):esc(c.note)}</span>${c.configured?`<div><button class="mini-btn" data-test-connection="${c.id}">Tester</button><button class="mini-btn" data-delete-connection="${c.id}">Oublier les clés</button></div>`:''}`});
  }
  async function saveConnection(form){const provider=form.dataset.provider,payload=Object.fromEntries(new FormData(form).entries());Object.keys(payload).forEach(key=>{if(payload[key]==='')delete payload[key]});const button=form.querySelector('button[type="submit"]');button.disabled=true;button.textContent='Vérification…';try{await fetchJson(`/api/connections/${provider}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});form.reset();toast('Connexion officielle vérifiée');await loadConnections();await loadRadar()}catch(e){modal('Connexion non validée',`<div class="error-box">${esc(e.message)}</div><p>Les identifiants saisis restent protégés dans votre espace pour pouvoir relancer le test.</p>`,'CONNEXION');await loadConnections()}finally{button.disabled=false;button.textContent='Enregistrer et tester'}}
  async function testConnection(provider){try{await fetchJson(`/api/connections/${provider}/test`,{method:'POST'});toast('Connexion vérifiée');await loadConnections();await loadRadar()}catch(e){modal('Test impossible',`<div class="error-box">${esc(e.message)}</div>`,'CONNEXION');await loadConnections()}}
  async function deleteConnection(provider){if(!confirm('Oublier les identifiants de cette connexion ?'))return;try{await fetchJson(`/api/connections/${provider}`,{method:'DELETE'});toast('Identifiants supprimés');await loadConnections();await loadRadar()}catch(e){toast(e.message)}}

  async function loadSettings(){
    try{
      const [e,r,sys,cj]=await Promise.all([fetchJson('/api/settings/ebay'),fetchJson('/api/settings/risk'),fetchJson('/api/ui/system'),fetchJson('/api/cj/settings')]); state.settings=e; state.risk=r;state.ebayConnected=!!e.connected;updateConnectionCount();
      $('#ebaySettingsStatus').textContent=e.connected?'Connecté':e.configured?'Clés enregistrées':'Non configuré'; $('#ebaySettingsStatus').className=`status-badge ${e.connected?'good':e.configured?'neutral':'neutral'}`;
      $('#clientId').placeholder=e.client_id_masked||'App ID / Client ID'; $('#runame').placeholder=e.runame_masked||'RuName eBay'; $('#clientSecret').placeholder=e.has_client_secret?'•••••••• (conservé si vide)':'Client Secret';
      $('#environment').value=e.environment; $('#marketplaceId').value=e.marketplace_id; $('#currency').value=e.currency;
      const rf=$('#riskSettingsForm'); Object.entries(r).forEach(([k,v])=>{if(rf.elements[k])rf.elements[k].value=v});
      renderSystem(sys); const oauth=$('#oauthButton'); oauth.textContent=e.connected?'Compte connecté ✓':e.configured?'Autoriser le compte eBay':'Enregistrer les clés d’abord'; oauth.disabled=!e.configured||e.connected;
      state.cjConnected=!!cj.connected; updateConnectionCount(); $('#cjSettingsStatus').textContent=cj.connected?'Connecté':cj.configured?'Clé enregistrée':'À connecter'; $('#cjSettingsStatus').className=`status-badge ${cj.connected?'good':'neutral'}`; $('#cjApiKey').placeholder=cj.configured?`${cj.api_key_masked} — laisser vide pour conserver`:'Collez la clé API copiée depuis CJ'; $('#testCjButton').disabled=!cj.configured;
    }catch(e){toast('Paramètres indisponibles : '+e.message);}
  }

  function renderSystem(s){ $('#systemDiagnostic').innerHTML=[['Version',s.version],['Python',s.python],['Environnement',s.environment],['Base de données',s.database_exists?'OK':'À créer'],['Mode démo',s.demo_mode?'Oui':'Non'],['Écriture eBay',s.write_enabled?'ACTIVE':'Bloquée'],['Publication',s.publish_enabled?'ACTIVE':'Bloquée'],['Accès',s.mode==='cloud'?'Cloud sécurisé':'Local']].map(([a,b])=>`<div class="diagnostic-item"><small>${esc(a)}</small><strong>${esc(b)}</strong></div>`).join(''); }

  async function saveEbaySettings(form){
    const fd=new FormData(form); const payload=Object.fromEntries(fd.entries());
    try{const d=await fetchJson('/api/settings/ebay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});toast('Paramètres eBay sauvegardés');await refreshSummary();await loadSettings();if(d.configured)modal('Configuration enregistrée','<div class="success-box"><strong>Les clés sont prêtes.</strong><p>Vous pouvez maintenant lancer l’autorisation OAuth Sandbox avec le bouton « Connecter le compte eBay ».</p></div>','EBAY');}
    catch(e){modal('Paramètres non enregistrés',`<div class="error-box">${esc(e.message)}</div>`,'EBAY');}
  }
  async function saveRiskSettings(form){
    const fd=new FormData(form), p={}; for(const [k,v] of fd.entries())p[k]=Number(v);
    try{const saved=await fetchJson('/api/settings/risk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});await Promise.all([loadSettings(),refreshAll()]);toast('Règles Risk Engine enregistrées et appliquées');modal('Règles appliquées',`<div class="success-box"><strong>Les nouveaux seuils sont actifs immédiatement.</strong><p>Les marges, blocages et scores produits viennent d’être recalculés.</p></div><div class="preview-block"><label>Contrôle</label><div>Marge minimum : ${Number(saved.applied.min_margin_percent).toFixed(1)} %\nProfit minimum : ${money(saved.applied.min_profit_eur)}\nStock minimum : ${saved.applied.min_stock}\nDélai maximum : ${saved.applied.max_shipping_days} jours</div></div>`,'RISK ENGINE');}
    catch(e){modal('Règles non enregistrées',`<div class="error-box">${esc(e.message)}</div>`,'RISK ENGINE');}
  }
  async function saveCjSettings(form){const key=new FormData(form).get('api_key')?.trim();if(!key){toast('Collez d’abord la clé API CJ');return}const button=form.querySelector('button[type="submit"]');button.disabled=true;button.textContent='Test de CJ…';try{const d=await fetchJson('/api/cj/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:key})});form.reset();modal('CJ connecté',`<div class="success-box"><strong>Connexion en lecture seule réussie.</strong><p>${d.warehouses} entrepôt(s) CJ détecté(s). Aucune commande et aucun produit n’ont été modifiés.</p></div>`,'FOURNISSEUR');await loadSettings();if(location.hash==='#suppliers')await loadCjCatalog()}catch(e){modal('Connexion CJ impossible',`<div class="error-box">${esc(e.message)}</div><p>Vérifiez que vous avez copié la clé de type API Key, et non le nom du magasin API.</p>`,'CJ')}finally{button.disabled=false;button.textContent='Enregistrer et tester'}}
  async function testCj(){try{const d=await fetchJson('/api/cj/test',{method:'POST'});toast(`CJ répond correctement · ${d.warehouses} entrepôt(s)`);await loadSettings()}catch(e){modal('Test CJ impossible',`<div class="error-box">${esc(e.message)}</div>`,'CJ')}}

  async function connectEbay(){
    try{const prep=await fetchJson('/api/auth/ebay/prepare');
      if(prep.connected){modal('Compte eBay connecté','<div class="success-box"><strong>OAuth actif ✓</strong><p>Le bot dispose déjà d’une autorisation eBay.</p></div>','EBAY');return;}
      if(!prep.ready){navigate('connections');await loadSettings();modal('Configuration eBay incomplète',`<div class="warn-box"><strong>Pas encore prêt à se connecter.</strong><p>${prep.missing?.length?'Il manque : '+prep.missing.map(esc).join(', '):esc(prep.error||'Vérifie les paramètres eBay.')}</p></div><p>Renseignez les clés dans Connexions. Si votre compte Developer est encore en attente d’approbation, vous pouvez continuer à préparer le catalogue.</p>`,'EBAY');return;}
      const authorizationUrl=safeUrl(prep.authorization_url);if(!authorizationUrl)throw new Error('L’adresse d’autorisation eBay est invalide.');window.location.assign(authorizationUrl);
    }catch(e){modal('Connexion eBay impossible',`<div class="error-box">${esc(e.message)}</div>`,'EBAY');}
  }

  function info(type){
    if(type==='environment') modal('Sandbox eBay','<div class="info-box"><strong>Environnement de test.</strong><p>Le bot ne touche pas à votre vraie boutique. C’est ici qu’on validera OAuth, listings et commandes de test.</p></div>','SÉCURITÉ');
    if(type==='demo') modal('Mode démo','<div class="info-box"><strong>Le bot fonctionne sans clés eBay.</strong><p>Le catalogue, les marges, le Risk Engine et les fiches locales peuvent être testés. Le Radar affiche uniquement des données issues de sources réellement connectées.</p></div>','STATUT');
    if(type==='safety') modal('Dry-run','<div class="success-box"><strong>Protection active.</strong><p>Les écritures et publications réelles restent verrouillées. On ne les activera qu’après validation complète du Sandbox.</p></div>','SÉCURITÉ');
  }

  async function refreshAll(){ await Promise.all([refreshSummary(),loadProducts()]); }

  document.addEventListener('click', e=>{
    const close=e.target.closest('[data-close-modal]'); if(close){closeModal();return;}
    const nav=e.target.closest('[data-section]'); if(nav){navigate(nav.dataset.section);return;}
    const go=e.target.closest('[data-go]'); if(go){navigate(go.dataset.go);return;}
    const infoBtn=e.target.closest('[data-info]'); if(infoBtn){info(infoBtn.dataset.info);return;}
    const gen=e.target.closest('[data-generate]'); if(gen){generateListing(gen.dataset.generate);return;}
    const scoreDetail=e.target.closest('[data-score-detail]');if(scoreDetail){showProductScore(scoreDetail.dataset.scoreDetail);return;}
    const suggest=e.target.closest('[data-suggest]'); if(suggest){suggestProduct(suggest.dataset.suggest);return;}
    const prepare=e.target.closest('[data-prepare]'); if(prepare){prepareProduct(prepare.dataset.prepare);return;}
    const editProduct=e.target.closest('[data-edit-product]'); if(editProduct){showAddProduct(state.products.find(p=>p.id===Number(editProduct.dataset.editProduct))||{});return;}
    const deleteProductButton=e.target.closest('[data-delete-product]'); if(deleteProductButton&&confirm('Supprimer ce produit ?')){safely(fetchJson(`/api/products/${deleteProductButton.dataset.deleteProduct}`,{method:'DELETE'}).then(refreshAll),'Suppression impossible');return;}
    const editSupplier=e.target.closest('[data-edit-supplier]'); if(editSupplier){showSupplier(state.suppliers.find(s=>s.id===Number(editSupplier.dataset.editSupplier))||{});return;}
    const deleteSupplierButton=e.target.closest('[data-delete-supplier]'); if(deleteSupplierButton&&confirm('Supprimer ce fournisseur ? Les produits seront conservés.')){safely(fetchJson(`/api/suppliers/${deleteSupplierButton.dataset.deleteSupplier}`,{method:'DELETE'}).then(()=>loadSuppliers()).then(loadProducts),'Suppression impossible');return;}
    const selectCjButton=e.target.closest('[data-select-cj]'); if(selectCjButton){selectCj(selectCjButton.dataset.selectCj);return;}
    const analyzeCjButton=e.target.closest('[data-open-cj-analysis]'); if(analyzeCjButton){openCjAnalysis(analyzeCjButton.dataset.openCjAnalysis);return;}
    const removeCjButton=e.target.closest('[data-remove-cj]'); if(removeCjButton){safely(fetchJson(`/api/cj/candidates/${removeCjButton.dataset.removeCj}`,{method:'DELETE'}).then(loadCjCandidates),'Retrait impossible');return;}
    const addCjButton=e.target.closest('[data-add-cj-product]');if(addCjButton){addCjProduct(addCjButton.dataset.addCjProduct);return;}
    const addSupplierOfferButton=e.target.closest('[data-add-supplier-offer]');if(addSupplierOfferButton){addSupplierOffer(addSupplierOfferButton.dataset.addSupplierOffer);return;}
    const addDirectory=e.target.closest('[data-add-directory]');if(addDirectory){addDirectorySupplier(addDirectory.dataset.addDirectory);return;}
    const goCjCandidate=e.target.closest('[data-go-cj-candidate]');if(goCjCandidate){navigate('suppliers');setTimeout(()=>$('#cjCandidates')?.scrollIntoView({behavior:'smooth',block:'center'}),150);return;}
    const moreCjButton=e.target.closest('[data-cj-more]'); if(moreCjButton){searchCj(true);return;}
    const financeDaysButton=e.target.closest('[data-finance-days]'); if(financeDaysButton){$('#financeDays').value=financeDaysButton.dataset.financeDays;$$('[data-finance-days]').forEach(x=>x.classList.toggle('active',x===financeDaysButton));loadFinance();return;}
    const deleteWatch=e.target.closest('[data-delete-watch]');if(deleteWatch){safely(fetchJson(`/api/radar/watchlist/${deleteWatch.dataset.deleteWatch}`,{method:'DELETE'}).then(loadRadar),'Suppression impossible');return;}
    const scanWatch=e.target.closest('[data-scan-watch]');if(scanWatch){$('#radarQuery').value=scanWatch.dataset.scanWatch;const ebay=state.radarSources.find(x=>x.id==='ebay'),amazon=state.radarSources.find(x=>x.id==='amazon');if(!ebay?.ready&&amazon?.ready){$$('input[name="radar_market"]').forEach(x=>x.checked=false);const amazonFr=$('input[name="amazon_market"][value="AMAZON_FR"]');if(amazonFr)amazonFr.checked=true}runRadarScan();return;}
    const signalWatch=e.target.closest('[data-signal-watch]');if(signalWatch){$('#radarSignalQuery').value=signalWatch.dataset.signalWatch;runSignalScan();return;}
    const testConnectionButton=e.target.closest('[data-test-connection]');if(testConnectionButton){testConnection(testConnectionButton.dataset.testConnection);return;}
    const deleteConnectionButton=e.target.closest('[data-delete-connection]');if(deleteConnectionButton){deleteConnection(deleteConnectionButton.dataset.deleteConnection);return;}
    const deleteFactory=e.target.closest('[data-delete-factory]');if(deleteFactory&&confirm('Supprimer ce contact fabricant ?')){safely(fetchJson(`/api/radar/factories/${deleteFactory.dataset.deleteFactory}`,{method:'DELETE'}).then(loadSupplierHub),'Suppression impossible');return;}
    const deleteRfq=e.target.closest('[data-delete-rfq]');if(deleteRfq&&confirm('Supprimer définitivement ce brouillon RFQ ?')){safely(fetchJson(`/api/radar/rfqs/${deleteRfq.dataset.deleteRfq}`,{method:'DELETE'}).then(loadSupplierHub),'Suppression impossible');return;}
    const viewRfq=e.target.closest('[data-view-rfq]');if(viewRfq){const r=state.rfqs.find(x=>x.id===Number(viewRfq.dataset.viewRfq));if(r)modal('Brouillon RFQ',`<div class="info-box"><strong>${esc(r.factory_company||'Sans destinataire')}</strong><p>Statut : ${esc(r.status)} · aucun envoi automatique.</p></div><div class="preview-block"><label>Message</label><div>${esc(r.message)}</div></div>`,'USINE');return;}
    const trend=e.target.closest('[data-trend-keyword]');if(trend){$('#radarSignalQuery').value=trend.dataset.trendKeyword;$('#radarQuery').value=trend.dataset.trendKeyword;$('#radarSignalForm').scrollIntoView({behavior:'smooth',block:'center'});toast('Produit prêt à être recoupé sur les réseaux et marketplaces');return;}
    const findSuppliers=e.target.closest('[data-find-suppliers]');if(findSuppliers){navigate('suppliers');setTimeout(()=>{$('#supplierMatchQuery').value=findSuppliers.dataset.findSuppliers;matchSuppliers()},120);return;}
    const useProvider=e.target.closest('[data-use-provider]');if(useProvider){if(useProvider.dataset.useProvider==='cj'){$('#cjSearchForm').scrollIntoView({behavior:'smooth',block:'center'});$('#cjQuery').focus()}else{$('#supplierMatchForm').scrollIntoView({behavior:'smooth',block:'center'});$('#supplierMatchQuery').focus()}return;}
    const prefillRfq=e.target.closest('[data-prefill-rfq]');if(prefillRfq){$('#rfqForm').elements.product_query.value=prefillRfq.dataset.prefillRfq;$('#rfqForm').scrollIntoView({behavior:'smooth',block:'center'});toast('Produit ajouté au brouillon RFQ');return;}
    const editSupport=e.target.closest('[data-edit-support]');if(editSupport){showSupportCase(state.supportCases.find(row=>row.id===Number(editSupport.dataset.editSupport))||{});return;}
    const draftSupport=e.target.closest('[data-draft-support]');if(draftSupport){draftSupportResponse(draftSupport.dataset.draftSupport);return;}
    const deleteSupport=e.target.closest('[data-delete-support]');if(deleteSupport&&confirm('Supprimer ce dossier SAV local ?')){safely(fetchJson(`/api/support/cases/${deleteSupport.dataset.deleteSupport}`,{method:'DELETE'}).then(loadSupport),'Suppression impossible');return;}
    const copySupport=e.target.closest('[data-copy-support-draft]');if(copySupport){const value=$('#supportDraftText')?.value||'';navigator.clipboard.writeText(value).then(()=>toast('Brouillon copié')).catch(()=>{const field=$('#supportDraftText');field?.select();toast('Texte sélectionné : utilisez Ctrl+C')});return;}
    const action=e.target.closest('[data-action]'); if(!action)return;
    const a=action.dataset.action;
    if(a==='load-demo')loadDemo(); if(a==='add-product')showAddProduct(); if(a==='add-supplier')showSupplier(); if(a==='add-support')showSupportCase(); if(a==='download-csv')downloadCsv(); if(a==='csv-help')csvHelp(); if(a==='connect-ebay')connectEbay();
    if(a==='radar-watch-current')saveRadarWatch($('#radarQuery').value);
  });
  document.addEventListener('change',e=>{if(e.target.matches('[data-status]'))changeStatus(e.target.dataset.status,e.target.value);if(e.target.matches('[data-supplier-import]'))importSupplier(e.target.files[0],e.target.dataset.supplierImport);if(e.target.matches('[data-support-status]'))safely(fetchJson(`/api/support/cases/${e.target.dataset.supportStatus}/status`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:e.target.value})}).then(loadSupport),'Statut SAV non modifié')});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});
  $('#mobileMenu').addEventListener('click',()=>$('.sidebar').classList.toggle('open'));
  $('#csvInput').addEventListener('change',e=>importCsv(e.target.files[0]));
  $('#cjSearchForm').addEventListener('submit',e=>{e.preventDefault();searchCj()});
  $('#financeFilters').addEventListener('submit',e=>{e.preventDefault();loadFinance()});
  $('#radarScanForm').addEventListener('submit',e=>{e.preventDefault();runRadarScan()});
  $('#radarSignalForm').addEventListener('submit',e=>{e.preventDefault();runSignalScan()});
  $('#radarWatchForm').addEventListener('submit',e=>{e.preventDefault();saveRadarWatch($('#radarWatchKeyword').value,$('#radarWatchNotes').value).then(saved=>{if(saved)e.target.reset()})});
  $('#supplierMatchForm').addEventListener('submit',e=>{e.preventDefault();matchSuppliers()});
  $('#supplierDirectoryFilters').addEventListener('submit',e=>{e.preventDefault();loadSupplierDirectory()});
  $('#factoryDiscoveryForm').addEventListener('submit',e=>{e.preventDefault();discoverFactories()});
  $('#factoryForm').addEventListener('submit',e=>{e.preventDefault();saveFactory(e.target)});
  $('#rfqForm').addEventListener('submit',e=>{e.preventDefault();createRfq(e.target)});
  $('#ebaySettingsForm').addEventListener('submit',e=>{e.preventDefault();saveEbaySettings(e.target)});
  $('#riskSettingsForm').addEventListener('submit',e=>{e.preventDefault();saveRiskSettings(e.target)});
  $('#cjSettingsForm').addEventListener('submit',e=>{e.preventDefault();saveCjSettings(e.target)}); $('#testCjButton').addEventListener('click',testCj);
  $$('.connection-form').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();saveConnection(e.target)}));
  $('#oauthButton').addEventListener('click',connectEbay); $('#refreshOrders').addEventListener('click',loadOrders); $('#refreshDiagnostic').addEventListener('click',()=>safely(fetchJson('/api/ui/system').then(renderSystem),'Diagnostic indisponible'));
  $('#exportDiagnostic')?.addEventListener('click',()=>safely(exportSafeDiagnostic(),'Export impossible'));
  $('#runAnalysis').addEventListener('click',runAnalysis); $('#readAlerts').addEventListener('click',async()=>{try{const d=await fetchJson('/api/automation/alerts/read',{method:'POST'});toast(d.updated?`${d.updated} alerte${d.updated>1?'s':''} marquée${d.updated>1?'s':''} comme lue${d.updated>1?'s':''}`:'Toutes les alertes sont déjà lues');await loadAutomation()}catch(e){toast('Impossible de mettre à jour les alertes : '+e.message)}});
  $('#runAutoDiscovery').addEventListener('click',runAutoDiscovery);$('#refreshOpportunities').addEventListener('click',()=>safely(loadOpportunities(),'Opportunités indisponibles'));
  document.addEventListener('submit',e=>{if(e.target.id==='addProductForm'){e.preventDefault();submitProduct(e.target)}});
  document.addEventListener('submit',e=>{if(e.target.id==='supplierForm'){e.preventDefault();saveSupplier(e.target)}});
  document.addEventListener('submit',e=>{if(e.target.id==='supportCaseForm'){e.preventDefault();saveSupportCase(e.target)}});
  document.addEventListener('submit',e=>{if(e.target.id==='cjAnalysisForm'){e.preventDefault();runCjCostAnalysis(e.target)}});
  ['filterText','filterSupplier','filterStatus','filterScore','filterMargin'].forEach(id=>$('#'+id)?.addEventListener(id==='filterText'?'input':'change',renderProducts));
  ['supportSearch','supportStatusFilter','supportPriorityFilter'].forEach(id=>$('#'+id)?.addEventListener(id==='supportSearch'?'input':'change',renderSupportCases));
  $('#refreshSupport').addEventListener('click',()=>safely(loadSupport(),'SAV indisponible'));
  $('#installAppButton')?.addEventListener('click',installApplication);
  $('#createBackupButton')?.addEventListener('click',()=>safely(createCloudBackup(),'Sauvegarde impossible'));
  $('#showBackupsButton')?.addEventListener('click',()=>safely(showBackups(),'Sauvegardes indisponibles'));
  $('#logoutButton')?.addEventListener('click',()=>safely(logoutCloud(),'Déconnexion impossible'));
  window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();deferredInstallPrompt=event;$('#installAppButton').textContent="Installer l'application"});
  window.addEventListener('appinstalled',()=>{deferredInstallPrompt=null;$('#installAppButton').textContent='Application installée';toast('Ops Bot est installé')});

  async function init(){
    if('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
    loadCloudStatus().catch(()=>{});
    try{await loadSuppliers();await refreshAll();}catch(e){modal('Le bot a démarré, mais le dashboard ne peut pas charger les données',`<div class="error-box">${esc(e.message)}</div><p>Utilise le fichier <strong>DIAGNOSTIC_WINDOWS.bat</strong> si le problème revient.</p>`,'DIAGNOSTIC');}
    const aliases={finder:'radar',automation:'catalog',cjcatalog:'suppliers',listings:'ebay',orders:'ebay'};
    const requested=location.hash.replace('#',''),hash=aliases[requested]||requested;navigate(pageMeta[hash]?hash:'overview');
    loadListings().catch(()=>{}); loadSettings().catch(()=>{}); loadConnections().catch(()=>{}); loadAutomation().catch(()=>{});
  }
  init();
})();
