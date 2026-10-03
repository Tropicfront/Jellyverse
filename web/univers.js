/*
 * Jellyfin Univers — bouton et panneau de progression dans l'interface web.
 * Chargé par le plugin « JavaScript Injector ». La progression est calculée
 * pour l'utilisateur connecté (chaque profil voit la sienne).
 */
(function () {
  'use strict';
  if (window.__jfUnivers) return;
  window.__jfUnivers = true;

  // ------------------------------------------------------------ configuration
  const SCRIPT = document.currentScript;
  const BASE = (window.JF_UNIVERS_URL ||
    (SCRIPT && SCRIPT.src ? SCRIPT.src.replace(/\/univers\.js.*$/, '') : '')).replace(/\/$/, '');
  const RAFRAICHIR_DONNEES_MS = 60 * 1000;
  const CACHE_PROGRESSION_MS = 20 * 1000;

  let donnees = null;          // { maj, univers: [...] }
  let erreurDonnees = null;
  const cacheProgression = new Map(); // id univers -> { t, infos }

  // ------------------------------------------------------------ utilitaires
  const norm = (id) => String(id || '').replace(/-/g, '').toLowerCase();
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function idCourant() {
    const m = location.href.match(/[?&]id=([0-9a-fA-F-]{32,36})/);
    return m ? norm(m[1]) : null;
  }

  function api() {
    const c = window.ApiClient;
    return c && typeof c.getCurrentUserId === 'function' && c.getCurrentUserId() ? c : null;
  }

  function naviguer(id) {
    if (!id) return;
    fermerPanneau();
    const c = api();
    const sid = c && typeof c.serverId === 'function' ? c.serverId() : null;
    location.hash = '#/details?id=' + norm(id) + (sid ? '&serverId=' + sid : '');
  }

  // ------------------------------------------------------------ données
  async function chargerDonnees() {
    if (!BASE) { erreurDonnees = 'Adresse de l\'application inconnue (JF_UNIVERS_URL).'; return; }
    if (location.protocol === 'https:' && BASE.startsWith('http:')) {
      erreurDonnees = 'Jellyfin est en HTTPS mais l\'application en HTTP : le navigateur bloque la connexion. Voir le README (reverse proxy).';
      return;
    }
    try {
      const r = await fetch(BASE + '/api/univers', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      donnees = await r.json();
      donnees.univers.forEach((u) => { u._membres = new Set(u.membres.map(norm)); });
      erreurDonnees = null;
    } catch (e) {
      erreurDonnees = 'Impossible de joindre l\'application Jellyfin Univers (' + BASE + ').';
      console.warn('[Jellyfin Univers]', e);
    }
  }

  function universDe(id) {
    if (!donnees || !id) return [];
    return donnees.univers.filter((u) => u._membres.has(id));
  }

  async function getJSON(chemin, params) {
    const c = api();
    const url = c.getUrl(chemin, params);
    if (typeof c.getJSON === 'function') return c.getJSON(url);
    const r = await fetch(url, { headers: { Authorization: 'MediaBrowser Token="' + c.accessToken() + '"' } });
    return r.json();
  }

  async function infosElements(ids) {
    const c = api();
    const res = new Map();
    for (let i = 0; i < ids.length; i += 100) {
      const lot = ids.slice(i, i + 100);
      const r = await getJSON('Items', { userId: c.getCurrentUserId(), ids: lot.join(','), enableUserData: true });
      (r.Items || []).forEach((it) => res.set(norm(it.Id), it));
    }
    return res;
  }

  async function progression(u, forcer) {
    const cache = cacheProgression.get(u.id);
    if (!forcer && cache && Date.now() - cache.t < CACHE_PROGRESSION_MS) return cache.infos;
    const ids = [...new Set(u.etapes.flatMap((e) => e.elements))];
    const infos = await infosElements(ids);
    cacheProgression.set(u.id, { t: Date.now(), infos });
    return infos;
  }

  function calculer(u, infos) {
    let vusTotal = 0, total = 0, prochain = null;
    const etapes = u.etapes.map((e, index) => {
      let vus = 0, enCours = false, premier = null;
      e.elements.forEach((id) => {
        const it = infos.get(norm(id));
        const ud = (it && it.UserData) || {};
        if (ud.Played) { vus++; return; }
        if (ud.PlaybackPositionTicks > 0) enCours = true;
        if (!premier) premier = { id, it, enCours: ud.PlaybackPositionTicks > 0, pct: ud.PlayedPercentage || 0 };
      });
      const n = e.elements.length;
      vusTotal += vus; total += n;
      let statut = 'avoir';
      if (!n) statut = 'absent';
      else if (vus === n) statut = 'fait';
      else if (vus || enCours) statut = 'encours';
      if (!prochain && n && vus < n) prochain = { index, etape: e, ...premier };
      return { ...e, index, vus, n, statut };
    });
    return { etapes, vusTotal, total, prochain };
  }

  function libelleElement(it) {
    if (!it) return '';
    if (it.Type === 'Episode') {
      const s = String(it.ParentIndexNumber ?? 0).padStart(2, '0');
      const e = String(it.IndexNumber ?? 0).padStart(2, '0');
      return (it.ParentIndexNumber === 0 ? 'Spécial ' + e : 'S' + s + 'E' + e) + ' · ' + it.Name;
    }
    return it.Name || '';
  }

  // ------------------------------------------------------------ image du parchemin
  const PARCHEMIN = `<svg class="jfu-svg" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect x="16" y="12" width="32" height="40" fill="#f3e0b5" stroke="#8b5e34" stroke-width="2"/>
    <g stroke="#a07a4b" stroke-width="2.4" stroke-linecap="round">
      <line x1="22" y1="22" x2="42" y2="22"/><line x1="22" y1="28" x2="42" y2="28"/>
      <line x1="22" y1="34" x2="38" y2="34"/><line x1="22" y1="40" x2="34" y2="40"/></g>
    <circle cx="40" cy="43" r="4.5" fill="#b23a3a" stroke="#7a1f1f" stroke-width="1.2"/>
    <rect x="10" y="7" width="44" height="9" rx="4.5" fill="#d8b27a" stroke="#8b5e34" stroke-width="2"/>
    <circle cx="10.5" cy="11.5" r="4" fill="#c4955a" stroke="#8b5e34" stroke-width="2"/>
    <rect x="10" y="48" width="44" height="9" rx="4.5" fill="#d8b27a" stroke="#8b5e34" stroke-width="2"/>
    <circle cx="53.5" cy="52.5" r="4" fill="#c4955a" stroke="#8b5e34" stroke-width="2"/>
  </svg>`;

  // ------------------------------------------------------------ styles
  const css = `
  .jfu-fond{position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.65);display:flex;
    align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(3px)}
  .jfu-panneau{background:#1c1c1e;color:#eee;border-radius:14px;width:100%;max-width:680px;max-height:86vh;
    overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.6);font-size:15px;line-height:1.45}
  .jfu-tete{display:flex;align-items:center;gap:10px;padding:18px 20px 8px;position:sticky;top:0;background:#1c1c1e;z-index:1}
  .jfu-tete h2{margin:0;font-size:1.35em;flex:1}
  .jfu-x,.jfu-retour{background:none;border:none;color:#aaa;font-size:20px;cursor:pointer;padding:4px 8px;border-radius:6px}
  .jfu-x:hover,.jfu-retour:hover{background:#333;color:#fff}
  .jfu-corps{padding:4px 20px 20px}
  .jfu-desc{color:#aaa;margin:0 0 14px}
  .jfu-barre{height:8px;background:#333;border-radius:4px;overflow:hidden}
  .jfu-barre>span{display:block;height:100%;background:linear-gradient(90deg,#00a4dc,#aa5cc3);border-radius:4px}
  .jfu-global{margin-bottom:16px}
  .jfu-global .jfu-chiffres{display:flex;justify-content:space-between;margin-bottom:6px;font-weight:600}
  .jfu-prochain{background:#26323a;border:1px solid #00a4dc55;border-radius:10px;padding:12px 14px;margin-bottom:16px;
    display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .jfu-prochain .jfu-txt{flex:1;min-width:200px}
  .jfu-prochain small{color:#9ad;display:block}
  .jfu-bouton{background:#00a4dc;color:#fff;border:none;border-radius:8px;padding:8px 14px;font-weight:600;cursor:pointer}
  .jfu-bouton:hover{filter:brightness(1.15)}
  .jfu-etapes{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
  .jfu-etape{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;background:#252527;cursor:pointer}
  .jfu-etape:hover{background:#2f2f33}
  .jfu-etape.absent{opacity:.5;cursor:default}
  .jfu-etape.suivante{outline:2px solid #00a4dc}
  .jfu-num{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font-weight:700;font-size:13px;background:#3a3a3c;flex-shrink:0}
  .jfu-etape.fait .jfu-num{background:#2e7d32}
  .jfu-etape.encours .jfu-num{background:#00a4dc}
  .jfu-info{flex:1;min-width:0}
  .jfu-info .jfu-t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .jfu-info .jfu-barre{height:4px;margin-top:6px}
  .jfu-compte{color:#aaa;font-size:.85em;white-space:nowrap}
  .jfu-liste-u{display:flex;flex-direction:column;gap:8px}
  .jfu-carte{background:#252527;border-radius:10px;padding:12px 14px;cursor:pointer}
  .jfu-carte:hover{background:#2f2f33}
  .jfu-carte .jfu-l1{display:flex;justify-content:space-between;margin-bottom:6px;font-weight:600}
  .jfu-pied{margin-top:16px;text-align:right}
  .jfu-lien{background:none;border:none;color:#00a4dc;cursor:pointer;font-size:.9em}
  .jfu-msg{color:#aaa;padding:10px 0}
  .jfu-parchemin .jfu-svg{width:2em;height:2em;display:block}
  .jfu-parchemin:hover .jfu-svg{transform:rotate(-6deg) scale(1.08);transition:transform .15s}
  .jfu-parchemin-flottant{position:fixed;right:20px;bottom:90px;z-index:9998;width:48px;height:48px;
    border-radius:50%;border:none;background:rgba(30,30,30,.85);cursor:pointer;padding:6px;display:none;
    box-shadow:0 4px 14px rgba(0,0,0,.5)}
  .jfu-parchemin-flottant .jfu-svg{width:100%;height:100%}
  .jfu-choix{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
  .jfu-bouton.secondaire{background:#3a3a3c}
  `;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);


  // ------------------------------------------------------------ panneau
  let fond = null;

  function fermerPanneau() {
    if (fond) { fond.remove(); fond = null; }
  }

  function ouvrirCadre(titre, avecRetour) {
    fermerPanneau();
    fond = document.createElement('div');
    fond.className = 'jfu-fond';
    fond.innerHTML = `<div class="jfu-panneau" role="dialog">
        <div class="jfu-tete">${avecRetour ? '<button class="jfu-retour" title="Tous les univers">←</button>' : ''}
          <h2>${esc(titre)}</h2><button class="jfu-x" title="Fermer">✕</button></div>
        <div class="jfu-corps"><div class="jfu-msg">Chargement…</div></div></div>`;
    fond.addEventListener('click', (e) => { if (e.target === fond) fermerPanneau(); });
    fond.querySelector('.jfu-x').onclick = fermerPanneau;
    const r = fond.querySelector('.jfu-retour');
    if (r) r.onclick = () => ouvrirListe();
    document.body.appendChild(fond);
    return fond.querySelector('.jfu-corps');
  }

  async function ouvrirListe() {
    const corps = ouvrirCadre('🌌 Mes univers', false);
    await chargerDonnees();
    if (erreurDonnees) { corps.innerHTML = `<div class="jfu-msg">${esc(erreurDonnees)}</div>`; return; }
    if (!donnees.univers.length) { corps.innerHTML = '<div class="jfu-msg">Aucun univers. Ajoute un fichier .yml dans univers/ (GitHub) ou dans /mnt/docker/jellyverse/data/univers/.</div>'; return; }
    corps.innerHTML = '<div class="jfu-liste-u"></div>';
    const liste = corps.querySelector('.jfu-liste-u');
    for (const u of donnees.univers) {
      const carte = document.createElement('div');
      carte.className = 'jfu-carte';
      carte.innerHTML = `<div class="jfu-l1"><span>${esc(u.nom)}</span><span class="jfu-compte">…</span></div>
        <div class="jfu-barre"><span style="width:0%"></span></div>`;
      carte.onclick = () => ouvrirUnivers(u, true);
      liste.appendChild(carte);
      progression(u).then((infos) => {
        const p = calculer(u, infos);
        const pct = p.total ? Math.round(100 * p.vusTotal / p.total) : 0;
        carte.querySelector('.jfu-compte').textContent = `${p.vusTotal}/${p.total} · ${pct} %${pct === 100 ? ' 🏁' : ''}`;
        carte.querySelector('.jfu-barre>span').style.width = pct + '%';
      }).catch(() => { carte.querySelector('.jfu-compte').textContent = 'erreur'; });
    }
  }

  async function ouvrirUnivers(u, avecRetour) {
    const corps = ouvrirCadre('🌌 ' + u.nom, avecRetour);
    let p;
    try {
      p = calculer(u, await progression(u, true));
    } catch (e) {
      corps.innerHTML = '<div class="jfu-msg">Impossible de lire la progression.</div>';
      console.warn('[Jellyfin Univers]', e);
      return;
    }
    const pct = p.total ? Math.round(100 * p.vusTotal / p.total) : 0;
    let html = '';
    if (u.description) html += `<p class="jfu-desc">${esc(u.description)}</p>`;
    html += `<div class="jfu-global"><div class="jfu-chiffres"><span>Progression</span>
        <span>${p.vusTotal}/${p.total} · ${pct} %</span></div>
        <div class="jfu-barre"><span style="width:${pct}%"></span></div></div>`;

    if (p.prochain) {
      html += `<div class="jfu-prochain"><div class="jfu-txt">
          <small>👉 ${p.prochain.enCours ? 'À reprendre' : 'Prochain à regarder'} — étape ${p.prochain.index + 1}</small>
          <strong>${esc(p.prochain.etape.titre)}</strong>
          ${p.prochain.it && p.prochain.it.Type === 'Episode' ? `<div>${esc(libelleElement(p.prochain.it))}</div>` : ''}
        </div><button class="jfu-bouton" data-id="${esc(p.prochain.id)}">Ouvrir</button></div>`;
    } else if (p.total) {
      html += '<div class="jfu-prochain"><div class="jfu-txt"><strong>🏁 Univers terminé !</strong></div></div>';
    }

    html += '<ol class="jfu-etapes">';
    p.etapes.forEach((e) => {
      const ep = e.n ? Math.round(100 * e.vus / e.n) : 0;
      const icone = { fait: '✓', encours: '▶', absent: '?', avoir: e.index + 1 }[e.statut];
      const compte = e.statut === 'absent' ? 'introuvable'
        : e.n > 1 ? `${e.vus}/${e.n} épisodes`
        : e.statut === 'fait' ? 'vu' : e.statut === 'encours' ? 'en cours' : 'à voir';
      const suivante = p.prochain && p.prochain.index === e.index ? ' suivante' : '';
      html += `<li class="jfu-etape ${e.statut}${suivante}" data-id="${esc(e.cible || '')}">
          <div class="jfu-num">${icone}</div>
          <div class="jfu-info"><div class="jfu-t">${esc(e.titre)}</div>
            ${e.n > 1 ? `<div class="jfu-barre"><span style="width:${ep}%"></span></div>` : ''}</div>
          <div class="jfu-compte">${compte}</div></li>`;
    });
    html += '</ol>';
    if (u.collection_id) html += `<div class="jfu-pied"><button class="jfu-lien" data-id="${esc(u.collection_id)}">Ouvrir la collection →</button></div>`;
    corps.innerHTML = html;

    corps.querySelectorAll('[data-id]').forEach((el) => {
      if (!el.dataset.id) return;
      el.addEventListener('click', () => naviguer(el.dataset.id));
    });
  }

  function ouvrirChoix(liste) {
    const corps = ouvrirCadre('📜 Univers liés', false);
    corps.innerHTML = '<div class="jfu-liste-u"></div>';
    const zone = corps.querySelector('.jfu-liste-u');
    liste.forEach((u) => {
      const carte = document.createElement('div');
      carte.className = 'jfu-carte';
      carte.innerHTML = `<div class="jfu-l1"><span>${esc(u.nom)}</span></div>
        <div class="jfu-choix">${u.collection_id ? '<button class="jfu-bouton" data-a="col">Ouvrir la collection</button>' : ''}
        <button class="jfu-bouton secondaire" data-a="prog">Progression</button></div>`;
      const col = carte.querySelector('[data-a="col"]');
      if (col) col.onclick = (e) => { e.stopPropagation(); naviguer(u.collection_id); };
      carte.querySelector('[data-a="prog"]').onclick = (e) => { e.stopPropagation(); ouvrirUnivers(u, false); };
      zone.appendChild(carte);
    });
  }

  // Bouton parchemin : film / série / saison / épisode → collection de l'univers ;
  // sur la page de la collection elle-même → panneau de progression.
  function clicParchemin(id) {
    const liste = universDe(id);
    if (!liste.length) return;
    const surCollection = liste.find((u) => norm(u.collection_id) === id);
    if (surCollection) return ouvrirUnivers(surCollection, false);
    if (liste.length > 1) return ouvrirChoix(liste);
    if (liste[0].collection_id) return naviguer(liste[0].collection_id);
    ouvrirUnivers(liste[0], false);
  }

  // ------------------------------------------------------------ médiathèque « Jellyverse »
  // Entrée ajoutée dans « Mes médias » et dans le menu latéral, copiée sur la
  // médiathèque « Collections » (même icône, même apparence). Elle ouvre la vue
  // native de Jellyfin filtrée sur le tag Jellyverse : grille, tris et filtres.
  const NOM_MEDIATHEQUE = 'Jellyverse';
  const TAG = 'Jellyverse';

  function urlMediatheque() {
    const c = api();
    const sid = c && typeof c.serverId === 'function' ? c.serverId() : '';
    return '#/list?type=BoxSet&tag=' + encodeURIComponent(TAG) + (sid ? '&serverId=' + sid : '');
  }

  function versMediatheque(e) {
    e.preventDefault();
    e.stopPropagation();
    location.hash = urlMediatheque();
  }

  function imageMediatheque() {
    const c = api();
    const u = donnees && donnees.univers.find((x) => x.collection_id);
    if (!c || !u || typeof c.getImageUrl !== 'function') return null;
    return c.getImageUrl(u.collection_id, { type: 'Backdrop', maxWidth: 800 });
  }

  function preparerCopie(el) {
    const url = urlMediatheque();
    [el, ...el.querySelectorAll('*')].forEach((n) => {
      ['data-action', 'data-id', 'data-serverid', 'data-type', 'data-collectiontype', 'data-isfolder',
        'data-index', 'data-prefix', 'data-itemid', 'data-src'].forEach((a) => n.removeAttribute(a));
      n.classList.remove('itemAction', 'Mui-selected', 'navMenuOption-selected');
      if (n.tagName === 'A') n.setAttribute('href', url);
    });
    el.querySelectorAll('.cardOverlayContainer, .cardIndicators, .btnCardOptions, canvas').forEach((n) => n.remove());
    el.classList.add('jfu-mediatheque');
    el.addEventListener('click', versMediatheque, true);
    return el;
  }

  function changerTexte(el, selecteurs) {
    for (const sel of selecteurs) {
      const t = el.querySelector(sel);
      if (t) { t.textContent = NOM_MEDIATHEQUE; return; }
    }
  }

  const estCollections = (a) => /[#/]boxsets\?/.test(a.getAttribute('href') || '');

  function injecterMediatheque() {
    const actif = donnees && donnees.mediatheque !== false && donnees.univers.some((u) => u.collection_id);
    if (!actif) { document.querySelectorAll('.jfu-mediatheque').forEach((n) => n.remove()); return; }

    // 1. Accueil — tuiles « Mes médias »
    document.querySelectorAll('.itemsContainer').forEach((cont) => {
      const cartes = [...cont.children].filter((c) => c.classList.contains('card') && c.dataset.type === 'CollectionFolder');
      if (!cartes.length || cont.querySelector(':scope > .jfu-mediatheque')) return;
      const modele = cartes.find((c) => c.dataset.collectiontype === 'boxsets') || cartes[cartes.length - 1];
      const copie = preparerCopie(modele.cloneNode(true));
      changerTexte(copie, ['.cardText', '.cardTextCentered']);
      const image = copie.querySelector('.cardImageContainer');
      const src = imageMediatheque();
      if (image && src) {
        image.classList.remove('lazy', 'defaultCardBackground');
        image.classList.add('coveredImage');
        image.style.backgroundImage = 'url("' + src + '")';
        image.querySelectorAll('.cardImageIcon, .material-icons').forEach((n) => n.remove());
      }
      modele.after(copie);
    });

    // 2. Accueil — boutons « Mes médias » (affichage compact)
    document.querySelectorAll('.homeLibraryButtonContainer').forEach((cont) => {
      if (cont.querySelector('.jfu-mediatheque')) return;
      const boutons = [...cont.querySelectorAll('a.homeLibraryButton')];
      if (!boutons.length) return;
      const modele = boutons.find(estCollections) || boutons[boutons.length - 1];
      const copie = preparerCopie(modele.cloneNode(true));
      changerTexte(copie, ['.homeLibraryText']);
      modele.after(copie);
    });

    // 3. Menu latéral — mise en page « Legacy »
    document.querySelectorAll('.libraryMenuOptions').forEach((cont) => {
      if (cont.querySelector('.jfu-mediatheque')) return;
      const liens = [...cont.querySelectorAll('a.navMenuOption')];
      if (!liens.length) return;
      const modele = liens.find(estCollections) || liens[liens.length - 1];
      const copie = preparerCopie(modele.cloneNode(true));
      changerTexte(copie, ['.navMenuOptionText']);
      modele.after(copie);
    });

    // 4. Menu latéral — mise en page « Modern » (par défaut dans Jellyfin 12)
    document.querySelectorAll('a[href]').forEach((a) => {
      if (!estCollections(a) || a.closest('.libraryMenuOptions, .homeLibraryButtonContainer, .card, .jfu-mediatheque')) return;
      const li = a.closest('li');
      if (!li || !li.parentElement || li.parentElement.querySelector(':scope > .jfu-mediatheque')) return;
      const copie = preparerCopie(li.cloneNode(true));
      changerTexte(copie, ['.MuiListItemText-primary', '.MuiTypography-root', '.MuiListItemText-root']);
      li.after(copie);
    });
  }

  // ------------------------------------------------------------ boutons
  const parcheminFlottant = document.createElement('button');
  parcheminFlottant.className = 'jfu-parchemin-flottant';
  parcheminFlottant.innerHTML = PARCHEMIN;
  parcheminFlottant.onclick = () => clicParchemin(idCourant());
  document.body.appendChild(parcheminFlottant);

  function titreParchemin(id, liste) {
    return liste.some((u) => norm(u.collection_id) === id)
      ? 'Progression de l\'univers'
      : 'Voir l\'univers : ' + liste.map((u) => u.nom).join(', ');
  }

  function boutonParchemin(id) {
    const liste = universDe(id);
    const zone = document.querySelector('.itemDetailPage:not(.hide) .mainDetailButtons');
    // Mise en page sans zone de boutons : parchemin flottant en bas à droite
    parcheminFlottant.style.display = liste.length && !zone ? 'block' : 'none';
    parcheminFlottant.title = liste.length ? titreParchemin(id, liste) : '';
    if (!zone) return;
    const existant = zone.querySelector('.jfu-parchemin');
    if (!liste.length) { if (existant) existant.remove(); return; }
    if (existant && existant.dataset.item === id) return;
    if (existant) existant.remove();
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'button-flat detailButton emby-button jfu-parchemin';
    b.dataset.item = id;
    b.title = titreParchemin(id, liste);
    b.innerHTML = '<div class="detailButton-content">' + PARCHEMIN + '</div>';
    b.onclick = () => clicParchemin(id);
    zone.appendChild(b);
  }

  function tick() {
    const connecte = !!api();
    const lecture = /\/(video|nowplaying|login|selectserver|wizard)/i.test(location.hash);
    if (!connecte || lecture) { parcheminFlottant.style.display = 'none'; return; }
    const id = idCourant();
    injecterMediatheque();
    if (id) boutonParchemin(id);
    else parcheminFlottant.style.display = 'none';
  }

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') fermerPanneau(); });
  chargerDonnees().then(tick);
  setInterval(chargerDonnees, RAFRAICHIR_DONNEES_MS);
  setInterval(tick, 700);
  console.log('[Jellyfin Univers] chargé depuis', BASE);
})();
