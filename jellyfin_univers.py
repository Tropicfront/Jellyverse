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
            IncludeItemTypes=types, Recursive="true", Limit=30,
        ).get("Items", [])
        if annee:
            items = [i for i in items if i.get("ProductionYear") == int(annee)]
        exacts = [i for i in items if cle(i.get("Name", "")) == cle(nom)]
        return (exacts or items or [None])[0]

    def episodes(self, serie_id):
        data = self.get(f"/Shows/{serie_id}/Episodes",
                        userId=self.user_id, enableUserData="true")
        return [e for e in data.get("Items", []) if e.get("LocationType") != "Virtual"]

    def collections(self):
        return self.get("/Items", userId=self.user_id,
                        IncludeItemTypes="BoxSet", Recursive="true").get("Items", [])

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

    cid = synchroniser_collection(jf, nom_collection, ids_collection)
    info["collection_id"] = cid
    info["membres"].add(cid)
    ecrire_description(jf, cid, texte)
    print(f"  ✔ collection « {nom_collection} » à jour")
    return info


def synchroniser_collection(jf, nom_collection, ids):
    col = next((c for c in jf.collections() if c.get("Name") == nom_collection), None)
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


def ecrire_description(jf, cid, texte):
    it = jf.item(cid)
    if it.get("Overview") == texte:
        return
    it["Overview"] = texte
    verrous = set(it.get("LockedFields") or [])
    verrous.add("Overview")  # empêche Jellyfin d'écraser la description
    it["LockedFields"] = sorted(verrous)
    jf.post(f"/Items/{cid}", json=it)


# ---------------------------------------------------------------- programme principal

ETAT = {"maj": None, "univers": []}  # données servies au bouton de l'interface
VERROU = threading.Lock()


def executer(cfg, dossiers, test):
    jf = Jellyfin(cfg["serveur"], cfg["cle_api"], cfg["utilisateur"])
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
}


def charger_config(chemin):
    cfg = {}
    if chemin.exists():
        cfg = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    for var, cle_cfg in ENV.items():
        if os.environ.get(var) not in (None, ""):
            cfg[cle_cfg] = os.environ[var]
    if str(cfg.get("description_html", "true")).lower() in ("false", "0", "non", "no"):
        cfg["description_html"] = False
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

    synchroniser_github(cfg, cache_github)
    if not args.boucle:
        executer(cfg, dossiers, args.test)
        return

    port = int(cfg.get("port_web", 8099) or 0)
    if port:
        demarrer_serveur(port)
    intervalle = float(cfg.get("intervalle_minutes", 15)) * 60
    print(f"Mise à jour toutes les {intervalle / 60:g} min et dès qu'un .yml local change.", flush=True)
    derniere_sig, dernier_passage = None, time.time()
    premier = True
    while True:
        if not premier and time.time() - dernier_passage >= intervalle:
            synchroniser_github(cfg, cache_github)
        sig = signature(dossiers)
        if premier or sig != derniere_sig or time.time() - dernier_passage >= intervalle:
            raison = ("démarrage" if premier else
                      "fichiers modifiés" if sig != derniere_sig else "planifiée")
            print(time.strftime(f"\n[%Y-%m-%d %H:%M:%S] mise à jour ({raison})"), flush=True)
            try:
                executer(cfg, dossiers, args.test)
            except Exception as e:  # noqa: BLE001
                print(f"✖ {e}", flush=True)
            derniere_sig, dernier_passage, premier = signature(dossiers), time.time(), False
        time.sleep(10)


if __name__ == "__main__":
    main()
