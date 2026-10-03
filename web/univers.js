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

  // ------------------------------------------------------------ styles
  const css = `
  .jfu-flottant{position:fixed;right:20px;bottom:90px;z-index:9998;width:48px;height:48px;border-radius:50%;
    border:none;background:rgba(30,30,30,.85);color:#fff;font-size:22px;cursor:pointer;
    box-shadow:0 4px 14px rgba(0,0,0,.5);transition:transform .15s,background .15s;display:none}
  .jfu-flottant:hover{transform:scale(1.08)}
  .jfu-flottant.actif{background:#00a4dc;animation:jfu-pulse 2s ease-out 1}
  @keyframes jfu-pulse{0%{box-shadow:0 0 0 0 rgba(0,164,220,.7)}100%{box-shadow:0 0 0 18px rgba(0,164,220,0)}}
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

  function ouvrirPour(id) {
    const liste = universDe(id);
    if (liste.length === 1) ouvrirUnivers(liste[0], true);
    else ouvrirListe();
  }

  // ------------------------------------------------------------ boutons
  const flottant = document.createElement('button');
  flottant.className = 'jfu-flottant';
  flottant.title = 'Univers';
  flottant.textContent = '🌌';
  flottant.onclick = () => ouvrirPour(idCourant());
  document.body.appendChild(flottant);

  function boutonDetail(id) {
    // Page de détail « Legacy » : on ajoute un bouton à côté de Lecture / Favori…
    const zone = document.querySelector('.itemDetailPage:not(.hide) .mainDetailButtons');
    if (!zone) return;
    const existant = zone.querySelector('.jfu-detail');
    const liste = universDe(id);
    if (!liste.length) { if (existant) existant.remove(); return; }
    if (existant && existant.dataset.item === id) return;
    if (existant) existant.remove();
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'button-flat detailButton emby-button jfu-detail';
    b.dataset.item = id;
    b.title = 'Univers : ' + liste.map((u) => u.nom).join(', ');
    b.innerHTML = '<div class="detailButton-content"><span class="material-icons detailButton-icon hub" aria-hidden="true">hub</span></div>';
    b.onclick = () => ouvrirPour(id);
    zone.appendChild(b);
  }

  let dernierUrl = '';
  function tick() {
    const connecte = !!api();
    const lecture = /\/(video|nowplaying|login|selectserver|wizard)/i.test(location.hash);
    flottant.style.display = connecte && !lecture ? 'block' : 'none';
    if (!connecte) return;
    const id = idCourant();
    const dedans = universDe(id).length > 0;
    if (location.href !== dernierUrl) {
      dernierUrl = location.href;
      flottant.classList.toggle('actif', dedans);
      flottant.title = dedans ? 'Univers : ' + universDe(id).map((u) => u.nom).join(', ') : 'Mes univers';
    }
    if (id) boutonDetail(id);
  }

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') fermerPanneau(); });
  chargerDonnees().then(tick);
  setInterval(chargerDonnees, RAFRAICHIR_DONNEES_MS);
  setInterval(tick, 700);
  console.log('[Jellyfin Univers] chargé depuis', BASE);
})();
