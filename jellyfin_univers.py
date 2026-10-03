#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jellyfin Univers
----------------
Lit chaque fichier .yml du dossier « univers/ », crée (ou met à jour) une
collection Jellyfin par univers, et écrit dans la description de cette
collection la liste ordonnée des étapes avec l'avancement de l'utilisateur.

Usage :
    python jellyfin_univers.py            # une mise à jour
    python jellyfin_univers.py --test     # vérifie les .yml sans rien modifier
    python jellyfin_univers.py --boucle   # tourne en continu (intervalle du config.yml)
"""

import argparse
import base64
import hashlib
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import sys
import tarfile
import time
import unicodedata
from pathlib import Path

try:
    import requests
    import yaml
except ImportError:
    sys.exit("Dépendances manquantes : pip install requests pyyaml")


# ---------------------------------------------------------------- utilitaires

def cle(texte):
    """'Mushi-Shi' et 'Mushishi' -> 'mushishi' (comparaison tolérante)."""
    texte = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", texte.lower())


def lire_episodes(valeur):
    """Accepte 3, [1, 2, 5] ou "1-10, 12"."""
    if valeur is None:
        return None
    if isinstance(valeur, int):
        return {valeur}
    if isinstance(valeur, list):
        res = set()
        for v in valeur:
            res |= lire_episodes(v)
        return res
    res = set()
    for morceau in str(valeur).split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if "-" in morceau:
            a, b = morceau.split("-", 1)
            res |= set(range(int(a), int(b) + 1))
        else:
            res.add(int(morceau))
    return res


# ---------------------------------------------------------------- API Jellyfin

class Jellyfin:
    def __init__(self, serveur, cle_api, utilisateur):
        self.base = serveur.rstrip("/")
        self.http = requests.Session()
        # Jellyfin 12.x n'accepte plus que ce format (X-Emby-Token et ?api_key=
        # sont refusés). Il fonctionne aussi avec les versions 10.x.
        self.http.headers.update({
            "Authorization": (
                'MediaBrowser Client="Jellyfin Univers", Device="script", '
                f'DeviceId="jellyfin-univers", Version="1.0", Token="{cle_api}"'
            ),
            "Content-Type": "application/json",
        })
        self.version = self._version()
        self.user_id = self._trouver_utilisateur(utilisateur)

    def _version(self):
        try:
            info = self.get("/System/Info/Public") or {}
            version = info.get("Version", "?")
            print(f"Connecté à Jellyfin {version} ({info.get('ServerName', '')})", flush=True)
            return version
        except requests.RequestException as e:
            raise SystemExit(f"Impossible de joindre Jellyfin sur {self.base} : {e}")

    def _req(self, methode, chemin, **kw):
        r = self.http.request(methode, self.base + chemin, timeout=30, **kw)
        if r.status_code == 401:
            raise SystemExit(
                "Jellyfin a refusé la connexion (401) : vérifie la clé API "
                "(Tableau de bord → Clés API).")
        r.raise_for_status()
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def get(self, chemin, **params):
        return self._req("GET", chemin, params=params)

    def post(self, chemin, params=None, json=None):
        return self._req("POST", chemin, params=params, json=json)

    def delete(self, chemin, **params):
        return self._req("DELETE", chemin, params=params)

    def _trouver_utilisateur(self, nom):
        for u in self.get("/Users"):
            if u["Name"].lower() == str(nom).lower():
                return u["Id"]
        raise SystemExit(f"Utilisateur Jellyfin « {nom} » introuvable.")

    def item(self, item_id):
        try:
            return self.get(f"/Items/{item_id}", userId=self.user_id)
        except requests.HTTPError as e:  # Jellyfin < 10.9 uniquement
            if e.response is not None and e.response.status_code in (404, 405):
                return self.get(f"/Users/{self.user_id}/Items/{item_id}")
            raise

    def chercher(self, nom, types, annee=None):
        items = self.get(
            "/Items", userId=self.user_id, searchTerm=nom,
            IncludeItemTypes=types, Recursive="true", Limit=30, Fields="ProviderIds",
        ).get("Items", [])
        if annee:
            items = [i for i in items if i.get("ProductionYear") == int(annee)]
        exacts = [i for i in items if cle(i.get("Name", "")) == cle(nom)]
        return (exacts or items or [None])[0]

    def episodes(self, serie_id):
        data = self.get(f"/Shows/{serie_id}/Episodes",
                        userId=self.user_id, enableUserData="true")
        return [e for e in data.get("Items", []) if e.get("LocationType") != "Virtual"]

    def dernier_vu(self):
        """Dernier épisode/film terminé par l'utilisateur (détection rapide des visionnages)."""
        items = self.get("/Items", userId=self.user_id, SortBy="DatePlayed", SortOrder="Descending",
                         Recursive="true", IncludeItemTypes="Episode,Movie", Filters="IsPlayed",
                         Limit=1, enableUserData="true").get("Items", [])
        if not items:
            return None
        return items[0]["Id"], (items[0].get("UserData") or {}).get("LastPlayedDate")

    def image(self, item_id, type_image):
        r = self.http.get(f"{self.base}/Items/{item_id}/Images/{type_image}", timeout=60)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "image/jpeg").split(";")[0]

    def envoyer_image(self, item_id, type_image, contenu, mime):
        """Jellyfin attend le contenu de l'image encodé en base64 dans le corps."""
        r = self.http.post(f"{self.base}/Items/{item_id}/Images/{type_image}",
                           data=base64.b64encode(contenu), headers={"Content-Type": mime}, timeout=120)
        r.raise_for_status()

    def supprimer(self, item_id):
        self._req("DELETE", f"/Items/{item_id}")

    def collections(self, champs=None):
        params = {"userId": self.user_id, "IncludeItemTypes": "BoxSet", "Recursive": "true"}
        if champs:
            params["Fields"] = champs
        return self.get("/Items", **params).get("Items", [])

    def enfants(self, parent_id):
        return self.get("/Items", userId=self.user_id, ParentId=parent_id).get("Items", [])


# ---------------------------------------------------------------- résolution d'une étape

def filtrer(episodes, etape):
    saison = etape.get("saison")
    numeros = lire_episodes(etape.get("episodes"))
    if saison is None:
        if not etape.get("inclure_speciaux", False):
            episodes = [e for e in episodes if e.get("ParentIndexNumber") != 0]
    else:
        episodes = [e for e in episodes if e.get("ParentIndexNumber") == int(saison)]
    if numeros:
        episodes = [e for e in episodes if e.get("IndexNumber") in numeros]
    return sorted(episodes, key=lambda e: (e.get("ParentIndexNumber") or 0, e.get("IndexNumber") or 0))


def resoudre(jf, etape):
    """Renvoie (id à mettre dans la collection, nom trouvé, liste d'éléments à regarder)."""
    if "id" in etape:
        it = jf.item(str(etape["id"]))
        t = it.get("Type")
        if t == "Series":
            return it["Id"], it["Name"], filtrer(jf.episodes(it["Id"]), etape)
        if t == "Season":
            eps = [e for e in jf.episodes(it["SeriesId"]) if e.get("SeasonId") == it["Id"]]
            return it["SeriesId"], f'{it.get("SeriesName")} — {it["Name"]}', eps
        if t == "Episode":
            return it["SeriesId"], f'{it.get("SeriesName")} — {it["Name"]}', [it]
        return it["Id"], it["Name"], [it]

    if "film" in etape:
        it = jf.chercher(etape["film"], "Movie", etape.get("annee"))
        return (it["Id"], it["Name"], [it]) if it else (None, None, [])

    if "serie" in etape:
        s = jf.chercher(etape["serie"], "Series", etape.get("annee"))
        if not s:
            return None, None, []
        return s["Id"], s["Name"], filtrer(jf.episodes(s["Id"]), etape)

    raise ValueError("l'étape doit contenir « serie », « film » ou « id »")


def etat(elements):
    vus = sum(1 for e in elements if (e.get("UserData") or {}).get("Played"))
    en_cours = any((e.get("UserData") or {}).get("PlaybackPositionTicks", 0) > 0
                   and not (e.get("UserData") or {}).get("Played") for e in elements)
    return vus, len(elements), en_cours


# ---------------------------------------------------------------- traitement d'un univers

def barre(p, n=20):
    plein = round(p * n)
    return "▰" * plein + "▱" * (n - plein)


def traiter(jf, fichier, cfg, test=False, source="local"):
    data = yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}
    nom = data.get("nom") or fichier.stem
    nom_collection = data.get("collection") or (cfg.get("prefixe_collection", "") + nom)
    etapes = data.get("etapes") or []

    print(f"\n=== {nom}  ({fichier.name} · {source}) ===")
    resultats, ids_collection = [], []
    info = {"id": fichier.stem, "nom": nom, "source": source,
            "description": str(data.get("description") or "").strip(),
            "collection_id": None, "etapes": [], "membres": set()}
    premier_parent = None
    for i, etape in enumerate(etapes, 1):
        titre = etape.get("titre") or etape.get("film") or etape.get("serie") or f"Étape {i}"
        try:
            parent_id, trouve, elements = resoudre(jf, etape)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ étape {i} « {titre} » : {e}")
            parent_id, trouve, elements = None, None, []
        if parent_id and parent_id not in ids_collection:
            ids_collection.append(parent_id)
        ids_elements = [e["Id"] for e in elements]
        info["etapes"].append({"titre": titre, "cible": parent_id, "elements": ids_elements})
        if parent_id:
            info["membres"].add(parent_id)
            premier_parent = premier_parent or parent_id
        for e in elements:
            info["membres"].add(e["Id"])
            if e.get("SeasonId"):
                info["membres"].add(e["SeasonId"])
        vus, total, en_cours = etat(elements)
        resultats.append({"titre": titre, "trouve": trouve, "vus": vus,
                          "total": total, "en_cours": en_cours})

    # Statuts + prochaine étape
    prochain_marque = False
    lignes = []
    total_vus = sum(r["vus"] for r in resultats)
    total_all = sum(r["total"] for r in resultats)
    for i, r in enumerate(resultats, 1):
        if r["total"] == 0:
            icone, detail = "❓", "introuvable dans la bibliothèque"
        elif r["vus"] == r["total"]:
            icone, detail = "✅", "terminé"
        else:
            icone = "▶️" if (r["vus"] or r["en_cours"]) else "⬜"
            detail = f'{r["vus"]}/{r["total"]} épisodes' if r["total"] > 1 else (
                "en cours" if r["en_cours"] else "à voir")
            if not prochain_marque:
                detail += "  👉 prochain"
                prochain_marque = True
        if r["total"] > 1 and icone == "✅":
            detail = f'{r["total"]}/{r["total"]} épisodes'
        lignes.append(f'{icone} {i}. {r["titre"]} — {detail}')
        print(f'  {icone} {i}. {r["titre"]}  →  {r["trouve"] or "RIEN TROUVÉ"}  [{r["vus"]}/{r["total"]}]')

    pct = total_vus / total_all if total_all else 0
    entete = f"Progression : {total_vus}/{total_all} — {round(pct * 100)} %"
    if total_all and total_vus == total_all:
        entete += "  🏁 Univers terminé !"
    blocs = []
    if data.get("description"):
        blocs.append(str(data["description"]).strip())
    blocs += [entete, barre(pct), ""] + lignes

    sep = "<br>" if cfg.get("description_html", True) else "\n"
    if sep == "<br>":
        blocs[blocs.index(entete)] = f"<b>{entete}</b>"
        if data.get("description"):
            blocs.insert(1, "")
    texte = sep.join(blocs)
    print(f"  {entete}")

    if test:
        return info
    if not ids_collection:
        print("  ⚠ aucun élément trouvé, collection non créée.")
        return info

    cid = synchroniser_collection(jf, cfg, info["id"], nom_collection, ids_collection)
    info["collection_id"] = cid
    info["membres"].add(cid)
    ecrire_description(jf, cid, texte, nom_collection)
    print(f"  ✔ collection « {nom_collection} » à jour")
    if cfg.get("_affiches"):
        try:
            gerer_affiches(jf, cfg, info["id"], data.get("affiche"), premier_parent, cid)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ affiche : {e}")
    return info


def synchroniser_collection(jf, cfg, uid, nom_collection, ids):
    # On retrouve d'abord la collection par son tag Jellyverse + nom, puis par nom seul
    collections = jf.collections(champs="Tags")
    col = (next((c for c in collections if c.get("Name") == nom_collection and TAG in (c.get("Tags") or [])), None)
           or next((c for c in collections if c.get("Name") == nom_collection), None))
    if col is None:
        r = jf.post("/Collections", params={"name": nom_collection, "ids": ",".join(ids)})
        return r["Id"]
    cid = col["Id"]
    actuels = {i["Id"] for i in jf.enfants(cid)}
    a_ajouter = [i for i in ids if i not in actuels]
    a_retirer = [i for i in actuels if i not in ids]
    if a_ajouter:
        jf.post(f"/Collections/{cid}/Items", params={"ids": ",".join(a_ajouter)})
    if a_retirer:
        jf.delete(f"/Collections/{cid}/Items", ids=",".join(a_retirer))
    return cid


TAG = "Jellyverse"  # permet aux autres applis / plugins de retrouver les collections : /Items?Tags=Jellyverse


def ecrire_description(jf, cid, texte, nom=None):
    it = jf.item(cid)
    tags = list(it.get("Tags") or [])
    if it.get("Overview") == texte and TAG in tags and (not nom or it.get("Name") == nom):
        return
    it["Overview"] = texte
    if nom:
        it["Name"] = nom
    if TAG not in tags:
        it["Tags"] = tags + [TAG]
    verrous = set(it.get("LockedFields") or [])
    verrous.update({"Overview", "Tags", "Name"})  # empêche Jellyfin d'écraser nom, description et tag
    it["LockedFields"] = sorted(verrous)
    jf.post(f"/Items/{cid}", json=it)


# ---------------------------------------------------------------- affiches (TMDB)
#
# Ordre de priorité pour l'affiche d'un univers :
#   1. /affiches/perso/<univers>.jpg|png|webp     (fichier déposé par l'utilisateur)
#   2. clé « affiche » du .yml : tmdb_collection / tmdb_serie / tmdb_film / url / fichier
#   3. automatique : TMDB du premier film / série trouvé (via ses identifiants Jellyfin)
#   4. sans clé TMDB : image Jellyfin du premier film / série
# Les images sont gardées dans /affiches/<univers>/ et TMDB n'est réinterrogé
# qu'au changement de source ou tous les 7 jours : très peu de requêtes.

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/original"
RECHARGER_TMDB_S = 7 * 24 * 3600
EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
GENRES_TMDB = {"tmdb_collection": "collection", "tmdb_serie": "tv", "tmdb_film": "movie"}


class Tmdb:
    def __init__(self, cle, langue="fr"):
        self.langue = str(langue or "fr").split("-")[0]
        self.http = requests.Session()
        self.params = {}
        if cle.startswith("eyJ"):  # jeton de lecture (v4)
            self.http.headers["Authorization"] = f"Bearer {cle}"
        else:                      # clé API (v3)
            self.params["api_key"] = cle

    def images(self, genre, tmdb_id):
        r = self.http.get(f"{TMDB_API}/{genre}/{tmdb_id}/images", timeout=20, params={
            **self.params, "include_image_language": f"{self.langue},null,en"})
        if r.status_code == 401:
            raise RuntimeError("clé TMDB refusée")
        r.raise_for_status()
        donnees = r.json()

        def choisir(liste, ordre):
            liste = sorted(liste, key=lambda i: (i.get("vote_average", 0), i.get("vote_count", 0)), reverse=True)
            for langue in ordre:
                for im in liste:
                    if im.get("iso_639_1") == langue:
                        return im["file_path"]
            return liste[0]["file_path"] if liste else None

        return (choisir(donnees.get("posters", []), [self.langue, None, "en"]),
                choisir(donnees.get("backdrops", []), [None, self.langue, "en"]))


def _sha(contenu):
    return hashlib.sha1(contenu).hexdigest()


def _mime(nom, contenu):
    if contenu[:4] == b"\x89PNG":
        return "image/png"
    if contenu[:4] == b"RIFF":
        return "image/webp"
    return EXT_MIME.get(Path(nom).suffix.lower(), "image/jpeg")


def gerer_affiches(jf, cfg, uid, reglage, premier_parent, cid):
    racine = cfg["_affiches"]
    tmdb = cfg.get("_tmdb")
    dossier = racine / uid
    dossier.mkdir(parents=True, exist_ok=True)
    chemin_etat = dossier / "etat.json"
    etat = json.loads(chemin_etat.read_text()) if chemin_etat.exists() else {}
    reglage = reglage or {}
    images = {}  # type Jellyfin -> (contenu, mime)

    # 1. fichier personnel
    perso = next((f for f in sorted((racine / "perso").glob(f"{uid}.*"))
                  if f.suffix.lower() in EXT_MIME), None) if (racine / "perso").is_dir() else None
    if perso:
        contenu = perso.read_bytes()
        images["Primary"] = (contenu, _mime(perso.name, contenu))
        source = f"perso:{_sha(contenu)}"
    elif isinstance(reglage, dict) and reglage.get("fichier"):
        f = racine / str(reglage["fichier"])
        contenu = f.read_bytes()
        images["Primary"] = (contenu, _mime(f.name, contenu))
        source = f"fichier:{_sha(contenu)}"
    elif isinstance(reglage, dict) and reglage.get("url"):
        source = f"url:{reglage['url']}"
        if etat.get("source") != source or not (dossier / "affiche").exists():
            r = requests.get(reglage["url"], timeout=60)
            r.raise_for_status()
            (dossier / "affiche").write_bytes(r.content)
    else:
        # 2-3. TMDB (identifiant du .yml, sinon celui du premier film / série)
        genre = tmdb_id = None
        if isinstance(reglage, dict):
            for cle_yml, g in GENRES_TMDB.items():
                if reglage.get(cle_yml):
                    genre, tmdb_id = g, reglage[cle_yml]
        if not tmdb_id and premier_parent:
            if etat.get("parent") == premier_parent and etat.get("tmdb_auto"):
                genre, tmdb_id = etat["tmdb_auto"]
            else:
                it = jf.item(premier_parent)
                ids = {k.lower(): v for k, v in (it.get("ProviderIds") or {}).items()}
                if ids.get("tmdb"):
                    genre = "tv" if it.get("Type") == "Series" else "movie"
                    tmdb_id = ids["tmdb"]
                    etat["tmdb_auto"] = [genre, tmdb_id]
                etat["parent"] = premier_parent
        if tmdb and tmdb_id:
            source = f"tmdb:{genre}:{tmdb_id}"
            perime = time.time() - etat.get("date", 0) > RECHARGER_TMDB_S
            if etat.get("source") != source or perime or not (dossier / "affiche").exists():
                affiche, fond = tmdb.images(genre, tmdb_id)
                for chemin_tmdb, nom in ((affiche, "affiche"), (fond, "fond")):
                    if chemin_tmdb:
                        r = requests.get(TMDB_IMG + chemin_tmdb, timeout=60)
                        r.raise_for_status()
                        (dossier / nom).write_bytes(r.content)
                etat["date"] = time.time()
                print(f"  🖼 affiche TMDB téléchargée ({genre} {tmdb_id})")
        elif premier_parent:
            # 4. sans TMDB : on reprend les images Jellyfin du premier élément
            source = f"jellyfin:{premier_parent}"
            if etat.get("source") != source or not (dossier / "affiche").exists():
                for type_image, nom in (("Primary", "affiche"), ("Backdrop", "fond")):
                    contenu, _ = jf.image(premier_parent, type_image)
                    if contenu:
                        (dossier / nom).write_bytes(contenu)
        else:
            return

    for type_image, nom in (("Primary", "affiche"), ("Backdrop", "fond")):
        if type_image not in images and (dossier / nom).exists():
            contenu = (dossier / nom).read_bytes()
            images[type_image] = (contenu, _mime(nom, contenu))

    # Envoi à Jellyfin uniquement si l'image ou la collection a changé
    envoye = etat.get("envoye", {})
    for type_image, (contenu, mime) in images.items():
        empreinte = f"{cid}:{_sha(contenu)}"
        if envoye.get(type_image) != empreinte:
            jf.envoyer_image(cid, type_image, contenu, mime)
            envoye[type_image] = empreinte
            print(f"  🖼 {'affiche appliquée' if type_image == 'Primary' else 'fond appliqué'} à la collection")
    etat.update({"source": source, "envoye": envoye})
    chemin_etat.write_text(json.dumps(etat, indent=2))


# ---------------------------------------------------------------- programme principal

ETAT = {"maj": None, "univers": []}  # données servies au bouton de l'interface
VERROU = threading.Lock()


def executer(jf, cfg, dossiers, test):
    fichiers = lister_univers(dossiers)
    if not fichiers:
        print("Aucun fichier d'univers trouvé (" +
              ", ".join(f"{src} : {d}" for src, d in dossiers) + ")")
    univers = []
    for f, source in fichiers:
        try:
            info = traiter(jf, f, cfg, test, source)
            if info:
                info["membres"] = sorted(info["membres"])
                univers.append(info)
        except Exception as e:  # noqa: BLE001
            print(f"  ✖ erreur sur {f.name} : {e}")
    with VERROU:
        ETAT["univers"] = univers
        ETAT["mediatheque"] = bool(cfg.get("mediatheque", True))
        ETAT["maj"] = time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- sources des fichiers d'univers
#
#   1. « image »  : dossier univers/ du dépôt, intégré dans l'image Docker au build
#   2. « github » : dossier univers/ du dépôt GitHub, téléchargé à chaque mise à jour
#                   (nouveaux univers disponibles sans reconstruire l'image)
#   3. « local »  : /data/univers, les fichiers de l'utilisateur
#
# Un fichier portant le même nom dans une source suivante remplace le précédent :
# l'utilisateur peut donc modifier un univers officiel en le copiant en local.

def lister_univers(dossiers):
    choisis = {}
    for source, dossier in dossiers:
        if not dossier or not dossier.is_dir():
            continue
        for f in sorted(list(dossier.glob("*.yml")) + list(dossier.glob("*.yaml"))):
            if f.name.startswith("_"):
                continue  # modèles / fichiers désactivés
            choisis[f.stem.lower()] = (f, source)
    return sorted(choisis.values(), key=lambda x: x[0].stem.lower())


def synchroniser_github(cfg, cache):
    """Télécharge l'archive du dépôt GitHub et en extrait les .yml du dossier d'univers.

    L'archive (codeload.github.com) n'est pas soumise à la limite de 60 requêtes/heure
    de l'API GitHub. Renvoie True si quelque chose a changé dans le cache.
    """
    depot = str(cfg.get("github_depot") or "").strip().strip("/")
    if not depot:
        return False
    branche = cfg.get("github_branche") or "main"
    chemin = [p for p in str(cfg.get("github_chemin") or "univers").strip("/").split("/") if p]
    entetes = {"User-Agent": "jellyverse"}
    if cfg.get("github_token"):  # dépôt privé : passage par l'API avec le jeton
        entetes["Authorization"] = f"Bearer {cfg['github_token']}"
        url = f"https://api.github.com/repos/{depot}/tarball/{branche}"
    else:
        url = f"https://codeload.github.com/{depot}/tar.gz/refs/heads/{branche}"
    try:
        r = requests.get(url, headers=entetes, timeout=60)
        if r.status_code == 404:
            raise RuntimeError(f"dépôt ou branche introuvable ({depot}, {branche})")
        r.raise_for_status()
        distants = {}
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as archive:
            for membre in archive.getmembers():
                morceaux = membre.name.split("/")[1:]  # retire « depot-branche/ »
                if (membre.isfile() and len(morceaux) == len(chemin) + 1
                        and morceaux[:-1] == chemin
                        and morceaux[-1].lower().endswith((".yml", ".yaml"))):
                    distants[morceaux[-1]] = archive.extractfile(membre).read()

        cache.mkdir(parents=True, exist_ok=True)
        change = False
        for nom, contenu in distants.items():
            cible = cache / nom
            if not cible.exists() or cible.read_bytes() != contenu:
                cible.write_bytes(contenu)
                change = True
        for ancien in list(cache.glob("*.yml")) + list(cache.glob("*.yaml")):
            if ancien.name not in distants:  # supprimé du dépôt
                ancien.unlink()
                change = True
        print(f"GitHub {depot}/{'/'.join(chemin)} ({branche}) : {len(distants)} fichier(s)"
              + (" — mis à jour" if change else ""), flush=True)
        return change
    except Exception as e:  # noqa: BLE001
        print(f"⚠ GitHub : {e} — utilisation des copies déjà présentes", flush=True)
        return False


# ---------------------------------------------------------------- serveur web (bouton Jellyfin)

DOSSIER_WEB = Path(__file__).resolve().parent / "web"


class Serveur(BaseHTTPRequestHandler):
    def _envoyer(self, code, corps, type_mime):
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        chemin = self.path.split("?")[0].rstrip("/")
        if chemin.endswith("/api/univers"):
            with VERROU:
                corps = json.dumps(ETAT, ensure_ascii=False).encode("utf-8")
            self._envoyer(200, corps, "application/json; charset=utf-8")
        elif chemin.endswith("/univers.js"):
            self._envoyer(200, (DOSSIER_WEB / "univers.js").read_bytes(),
                          "application/javascript; charset=utf-8")
        elif chemin.endswith("/sante"):
            self._envoyer(200, b"ok", "text/plain")
        else:
            self._envoyer(404, b"introuvable", "text/plain")

    def log_message(self, *args):  # silence
        pass


def demarrer_serveur(port):
    serveur = ThreadingHTTPServer(("0.0.0.0", port), Serveur)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    print(f"Serveur du bouton Jellyfin actif sur le port {port} "
          f"(script : /univers.js, données : /api/univers)", flush=True)


ENV = {  # variables d'environnement (Docker) -> clés de config
    "JELLYFIN_URL": "serveur",
    "JELLYFIN_API_KEY": "cle_api",
    "JELLYFIN_USER": "utilisateur",
    "DOSSIER_UNIVERS": "dossier_univers",
    "DOSSIER_OFFICIEL": "dossier_officiel",
    "GITHUB_DEPOT": "github_depot",
    "GITHUB_BRANCHE": "github_branche",
    "GITHUB_CHEMIN": "github_chemin",
    "GITHUB_TOKEN": "github_token",
    "PREFIXE_COLLECTION": "prefixe_collection",
    "INTERVALLE_MINUTES": "intervalle_minutes",
    "DESCRIPTION_HTML": "description_html",
    "PORT_WEB": "port_web",
    "DETECTION_LECTURE_SECONDES": "detection_lecture_secondes",
    "TMDB_API_KEY": "tmdb_cle",
    "TMDB_LANGUE": "tmdb_langue",
    "DOSSIER_AFFICHES": "dossier_affiches",
    "MEDIATHEQUE": "mediatheque",
}


def charger_config(chemin):
    cfg = {}
    if chemin.exists():
        cfg = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    for var, cle_cfg in ENV.items():
        if os.environ.get(var) not in (None, ""):
            cfg[cle_cfg] = os.environ[var]
    for booleen in ("description_html", "mediatheque"):
        if str(cfg.get(booleen, "true")).lower() in ("false", "0", "non", "no"):
            cfg[booleen] = False
    manquants = [c for c in ("serveur", "cle_api", "utilisateur") if not cfg.get(c)]
    if manquants:
        raise SystemExit(f"Configuration incomplète : {', '.join(manquants)} "
                         "(config.yml ou variables JELLYFIN_URL / JELLYFIN_API_KEY / JELLYFIN_USER)")
    return cfg


def signature(dossiers):
    """Empreinte des fichiers .yml : change dès qu'un fichier est ajouté, modifié ou supprimé."""
    sig = []
    for source, dossier in dossiers:
        if dossier and dossier.is_dir():
            for f in list(dossier.glob("*.yml")) + list(dossier.glob("*.yaml")):
                sig.append((source, f.name, f.stat().st_mtime))
    return sorted(sig)


def main():
    ap = argparse.ArgumentParser(description="Jellyverse — fiches d'univers pour Jellyfin")
    ap.add_argument("--config", default=os.environ.get("CONFIG", "config.yml"))
    ap.add_argument("--test", action="store_true", help="vérifie sans rien modifier")
    ap.add_argument("--boucle", action="store_true", help="mise à jour en continu")
    args = ap.parse_args()

    chemin_cfg = Path(args.config).resolve()
    cfg = charger_config(chemin_cfg)

    local = Path(cfg.get("dossier_univers", "univers"))
    if not local.is_absolute():
        local = (chemin_cfg.parent / local).resolve()
    local.mkdir(parents=True, exist_ok=True)
    officiel = Path(cfg.get("dossier_officiel") or Path(__file__).resolve().parent / "univers")
    cache_github = local.parent / ".cache-github"

    dossiers = [("image", officiel), ("github", cache_github), ("local", local)]
    print("Sources des univers :", flush=True)
    print(f"  • image  : {officiel}", flush=True)
    if cfg.get("github_depot"):
        print(f"  • github : {cfg['github_depot']} / {cfg.get('github_chemin') or 'univers'}", flush=True)
    print(f"  • local  : {local}  (prioritaire en cas de même nom)", flush=True)

    affiches = Path(cfg.get("dossier_affiches") or (local.parent.parent / "affiches"))
    try:
        affiches.mkdir(parents=True, exist_ok=True)
        cfg["_affiches"] = affiches
        print(f"  • affiches : {affiches}", flush=True)
    except OSError as e:
        print(f"⚠ dossier des affiches inutilisable ({e}) : affiches désactivées", flush=True)
    if cfg.get("tmdb_cle"):
        cfg["_tmdb"] = Tmdb(str(cfg["tmdb_cle"]), cfg.get("tmdb_langue", "fr"))
        print("  • TMDB : activé", flush=True)
    else:
        print("  • TMDB : pas de clé, affiches reprises depuis Jellyfin", flush=True)

    print(f"  • médiathèque Jellyverse : {'affichée' if cfg.get('mediatheque', True) else 'désactivée'} "
          "(interface web)", flush=True)

    synchroniser_github(cfg, cache_github)
    if not args.boucle:
        executer(Jellyfin(cfg["serveur"], cfg["cle_api"], cfg["utilisateur"]), cfg, dossiers, args.test)
        return

    port = int(cfg.get("port_web", 8099) or 0)
    if port:
        demarrer_serveur(port)
    intervalle = float(cfg.get("intervalle_minutes", 15)) * 60
    detection = float(cfg.get("detection_lecture_secondes", 60) or 0)
    print(f"Mise à jour toutes les {intervalle / 60:g} min, dès qu'un .yml local change"
          + (f" et moins de {detection:g} s après la fin d'un épisode." if detection else "."), flush=True)

    jf = None
    derniere_sig, dernier_passage, dernier_controle, dernier_vu = None, 0.0, 0.0, None
    premier = True
    while True:
        try:
            if jf is None:
                jf = Jellyfin(cfg["serveur"], cfg["cle_api"], cfg["utilisateur"])
            maintenant = time.time()
            raison = None
            if premier:
                raison = "démarrage"
            elif maintenant - dernier_passage >= intervalle:
                synchroniser_github(cfg, cache_github)
                raison = "planifiée"
            sig = signature(dossiers)
            if raison is None and sig != derniere_sig:
                raison = "fichiers modifiés"
            if detection and maintenant - dernier_controle >= detection:
                dernier_controle = maintenant
                vu = jf.dernier_vu()
                if raison is None and vu != dernier_vu and vu and dernier_vu is not None:
                    with VERROU:
                        concerne = any(norm_id(vu[0]) in {norm_id(m) for m in u["membres"]}
                                       for u in ETAT["univers"])
                    if concerne:
                        raison = "épisode / film terminé"
                dernier_vu = vu
            if raison:
                print(time.strftime(f"\n[%Y-%m-%d %H:%M:%S] mise à jour ({raison})"), flush=True)
                executer(jf, cfg, dossiers, args.test)
                derniere_sig, dernier_passage, premier = signature(dossiers), time.time(), False
        except SystemExit as e:
            print(f"✖ {e} — nouvel essai dans 1 min", flush=True)
            jf = None
            time.sleep(50)
        except Exception as e:  # noqa: BLE001
            print(f"✖ {e}", flush=True)
            jf = None
        time.sleep(10)


def norm_id(i):
    return str(i or "").replace("-", "").lower()


if __name__ == "__main__":
    main()
