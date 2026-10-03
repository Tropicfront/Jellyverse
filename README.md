# Jellyverse

Crée dans Jellyfin une **fiche (collection) par univers**. En cliquant dessus, la
description affiche l'ordre de visionnage que tu as défini et ton avancement :

```
Progression : 31/64 — 48 %
▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱

✅ 1. Mushishi (Saison 1 — 26 épisodes) — 26/26 épisodes
✅ 2. L'Ombre qui dore le soleil (OVA) — terminé
▶️ 3. Le Suivant (Saison 2, Partie 1) — 4/10 épisodes  👉 prochain
⬜ 4. Le Chemin des épines (OVA) — à voir
⬜ 5. Le Suivant – Saison 2 (Partie 2) — 0/10 épisodes
⬜ 6. Les Gouttes de roches (Film) — à voir
```

## Structure

```
jellyverse/                    ← dépôt GitHub
├── docker-compose.yml         ← réglages de connexion
├── Dockerfile
├── jellyfin_univers.py
├── requirements.txt
├── web/univers.js             ← bouton + panneau injectés dans Jellyfin
├── univers/                   ← univers OFFICIELS (partagés via GitHub)
│   ├── mushishi.yml           ← un fichier = une fiche
│   └── _modele.yml.exemple
└── data/                      ← à copier dans /mnt/docker/jellyverse/data
    ├── config.yml
    └── univers/               ← univers LOCAUX de l'utilisateur
        └── LISEZMOI.txt
```

Sur la machine Docker :

```
/mnt/docker/jellyverse/
├── data/          ← config.yml + univers/*.yml (tes fichiers)
└── affiches/      ← créé automatiquement
    ├── mushishi/  ← affiche + fond téléchargés, etat.json
    └── perso/     ← tes propres affiches (facultatif) : mushishi.jpg …
```

Jellyverse n'a **pas besoin d'accéder aux dossiers de Jellyfin** : tout passe
par l'API. Jellyfin peut être sur une autre machine.

## D'où viennent les univers ?

Trois sources sont lues et fusionnées :

| Source     | Emplacement                                   | Mise à jour |
|------------|-----------------------------------------------|-------------|
| **image**  | dossier `univers/` du dépôt, copié dans l'image au `docker build` | à chaque nouvelle image |
| **github** | dossier `univers/` du dépôt GitHub (`GITHUB_DEPOT`), téléchargé par le conteneur | toutes les `INTERVALLE_MINUTES`, sans reconstruire l'image |
| **local**  | `/mnt/docker/jellyverse/data/univers/` sur la machine | quelques secondes après l'ajout d'un fichier |

- Un univers poussé sur GitHub apparaît donc tout seul, même avec une
  ancienne image. Si GitHub est injoignable, la dernière copie téléchargée
  (ou celle de l'image) est utilisée.
- **Le local est prioritaire** : un fichier local qui porte le même nom qu'un
  univers officiel (ex. `mushishi.yml`) le remplace. Pratique pour adapter
  un univers officiel à l'organisation de sa propre bibliothèque.
- Les fichiers dont le nom commence par `_` sont ignorés (modèles).
- Au démarrage, les logs indiquent la source de chaque univers :
  `=== Mushishi  (mushishi.yml · github) ===`.

## Installation

1. Dans Jellyfin : **Tableau de bord → Clés API → +**, copie la clé.
2. Crée le dossier local et copie-y le contenu de `data/` :
   ```bash
   sudo mkdir -p /mnt/docker/jellyverse/data/univers /mnt/docker/jellyverse/affiches/perso
   sudo cp -r data/* /mnt/docker/jellyverse/data/
   ```
   (sur un NAS, tu peux choisir un autre chemin : modifie alors la ligne
   `volumes` du `docker-compose.yml`).
3. Dans `docker-compose.yml`, renseigne `JELLYFIN_URL`, `JELLYFIN_API_KEY`,
   `JELLYFIN_USER` et `GITHUB_DEPOT` (ton `compte/dépôt`).
   - Jellyfin sur une autre machine : mets son adresse, par exemple
     `http://192.168.1.20:8096`.
   - Jellyfin sur la même machine dans un autre compose : tu peux aussi
     décommenter la partie `networks` et utiliser `http://jellyfin:8096`.
4. Vérifie tes fichiers sans rien modifier :
   ```bash
   docker compose run --rm jellyverse --test
   ```
5. Lance l'application :
   ```bash
   docker build -t tropicfront/jellyverse .
   docker compose up -d
   docker compose logs -f
   ```

## Fréquence de mise à jour

| Déclencheur | Délai |
|---|---|
| Épisode ou film d'un univers terminé par `JELLYFIN_USER` | moins d'1 min (`DETECTION_LECTURE_SECONDES`) |
| `.yml` ajouté / modifié / supprimé en local | ~10 s |
| Mise à jour complète + synchro GitHub | toutes les 15 min (`INTERVALLE_MINUTES`) |

La détection rapide ne coûte qu'une petite requête par minute : Jellyverse
demande à Jellyfin le dernier élément terminé, et ne relance une mise à jour
que s'il fait partie d'un univers. Le **panneau de progression**, lui, est toujours calculé
en direct à l'ouverture, pour l'utilisateur connecté.

## Médiathèque « Jellyverse »

Une entrée **« Jellyverse »** est ajoutée dans **Mes médias** (accueil) et dans
le **menu latéral**, juste après « Collections ». Elle est copiée sur la
médiathèque « Collections » : même icône, même apparence. Elle ouvre la vue
native de Jellyfin qui n'affiche **que les collections créées par
l'application** (filtrées par leur tag `Jellyverse`), avec la grille
d'affiches, les tris et les filtres habituels. La tuile d'accueil prend le fond
d'un de tes univers.

Comment ça marche : Jellyfin range toujours les collections créées par l'API
dans sa médiathèque « Collections », et une vraie médiathèque séparée
demanderait d'écrire dans les dossiers du serveur Jellyfin. Jellyverse évite
donc tout accès aux fichiers : les collections restent dans « Collections »
(elles y sont aussi visibles), et la médiathèque « Jellyverse » est une vue
filtrée ajoutée par le script de l'interface. `MEDIATHEQUE=false` la retire.

> Comme le bouton parchemin, cette entrée existe dans l'interface web (et les
> applis qui l'utilisent), pas dans les applis TV natives.

## Utilisation par d'autres applications

Les collections Jellyverse portent le tag **`Jellyverse`**, ce qui permet aux
autres applications et plugins de les retrouver par l'API :
`GET /Items?Recursive=true&IncludeItemTypes=BoxSet&Tags=Jellyverse`.

## Affiches des collections

Chaque collection reçoit une **affiche** et un **fond**, par ordre de priorité :

1. `/mnt/docker/jellyverse/affiches/perso/<univers>.jpg` (ou `.png`, `.webp`) :
   ton image à toi, le nom est celui du fichier `.yml` (ex. `mushishi.jpg`) ;
2. le bloc `affiche:` du `.yml` (`tmdb_collection`, `tmdb_serie`, `tmdb_film`,
   `url` ou `fichier`) ;
3. **automatique** : l'affiche TMDB du premier film / série de l'univers,
   grâce à l'identifiant TMDB déjà connu de Jellyfin ;
4. sans clé TMDB : les images Jellyfin de ce premier film / série.

TMDB : crée une clé gratuite sur themoviedb.org (Paramètres → API) et mets-la
dans `TMDB_API_KEY` (clé v3 ou jeton de lecture v4). Les affiches en français
sont choisies en priorité, les fonds sans texte de préférence. Les images sont
stockées dans `/mnt/docker/jellyverse/affiches/` : TMDB n'est réinterrogé que si
la source change ou tous les 7 jours, soit **une requête par univers et par
semaine** environ. Les images ne sont renvoyées à Jellyfin que si elles changent.

## Bouton dans l'interface Jellyfin

L'application ajoute dans l'interface web de Jellyfin :

- un **bouton parchemin 📜** à côté de Lecture / Favori sur la page de chaque
  film, série, saison ou épisode d'un univers : il ouvre la **collection** de
  l'univers (si l'élément appartient à plusieurs univers, une fenêtre propose le
  choix). Sur la page de la collection, il ouvre le panneau de progression ;
- un **panneau** avec l'ordre, la progression, l'étape en cours et un bouton
  « Ouvrir » qui mène directement au prochain épisode ou film à regarder
  (ouvert par le parchemin depuis la page de la collection).

La progression du panneau est celle **de l'utilisateur connecté** : chaque
profil voit sa propre avancée (contrairement à la description de la collection).

### Installation

1. Dans Jellyfin : **Tableau de bord → Extensions → Dépôts**, ajoute le dépôt
   de n00bcodr pour Jellyfin 12 :
   `https://raw.githubusercontent.com/n00bcodr/jellyfin-plugins/main/12/manifest.json`
2. Installe **JavaScript Injector** (et, conseillé, **File Transformation**),
   puis redémarre Jellyfin.
3. Ouvre la configuration de JavaScript Injector, ajoute un script et colle
   (en remplaçant l'adresse par celle de ta machine Docker) :

   ```js
   (function () {
     var s = document.createElement('script');
     s.src = 'http://192.168.1.10:8099/univers.js';
     document.head.appendChild(s);
   })();
   ```
4. Enregistre, puis recharge la page Jellyfin (Ctrl + F5).

L'adresse doit être joignable **par ton navigateur** (pas seulement par
Jellyfin) : c'est pour ça que le port `8099` est publié dans `docker-compose.yml`.
Pour vérifier, ouvre `http://IP:8099/api/univers` dans ton navigateur
(chaque univers y indique sa `source`).

### Jellyfin en HTTPS (reverse proxy)

Si tu accèdes à Jellyfin en `https://`, le navigateur bloque un script en
`http://`. Expose l'application derrière le même reverse proxy, par exemple
`https://jellyfin.mondomaine.fr/univers/` → `http://jellyverse:8099/`,
et utilise `https://jellyfin.mondomaine.fr/univers/univers.js` dans le script.

Exemple Nginx :

```nginx
location /univers/ {
    proxy_pass http://jellyverse:8099/;
}
```

### Limites

- Le bouton existe dans l'**interface web** (navigateur, application de bureau,
  et les applis mobiles qui affichent l'interface web). Les applis TV natives
  (Android TV, Swiftfin…) n'exécutent pas ce script : elles n'ont que la
  description de la collection.
- Si la page de détail n'a pas de zone de boutons (autre mise en page), le
  parchemin s'affiche en bouton flottant, en bas à droite.

## Ajouter un univers

- **Pour tout le monde** : ajoute le `.yml` dans `univers/` du dépôt et pousse-le
  sur GitHub. Chaque installation le récupère à la prochaine mise à jour.
- **Pour toi seulement** : dépose le `.yml` dans
  `/mnt/docker/jellyverse/data/univers/`. Rien à redémarrer.

Voir `univers/mushishi.yml` et `univers/_modele.yml.exemple`.

| Clé        | Exemple                          | Rôle                                  |
|------------|----------------------------------|---------------------------------------|
| `serie`    | `"Mushishi"`                     | nom de la série dans Jellyfin         |
| `saison`   | `1` (0 = spéciaux/OVA)           | limite à une saison                   |
| `episodes` | `3`, `[1, 4]`, `"1-10, 12"`      | limite à certains épisodes            |
| `film`     | `"Mushishi: Suzu no Shizuku"`    | nom du film dans Jellyfin             |
| `id`       | `"4f2a…"`                        | identifiant exact (série, saison, épisode ou film) |
| `titre`    | texte libre                      | ce qui s'affiche sur la fiche         |
| `annee`    | `2015`                           | départage deux titres identiques      |

**Trouver un `id`** : ouvre l'élément dans Jellyfin, l'adresse contient
`…details?id=XXXXXXXX`.

## Variables d'environnement

| Variable              | Défaut               | Rôle                                   |
|-----------------------|----------------------|----------------------------------------|
| `JELLYFIN_URL`        | —                    | adresse du serveur                     |
| `JELLYFIN_API_KEY`    | —                    | clé API                                |
| `JELLYFIN_USER`       | —                    | utilisateur dont on suit la progression|
| `INTERVALLE_MINUTES`  | `15`                 | mise à jour planifiée                  |
| `PREFIXE_COLLECTION`  | `""`                 | préfixe du nom des collections         |
| `DESCRIPTION_HTML`    | `true`               | `false` si des `<br>` s'affichent      |
| `PORT_WEB`            | `8099`               | port du bouton (`0` pour le désactiver)|
| `GITHUB_DEPOT`        | —                    | `compte/dépôt` des univers officiels (vide = désactivé) |
| `GITHUB_BRANCHE`      | `main`               | branche à lire                         |
| `GITHUB_CHEMIN`       | `univers`            | dossier des `.yml` dans le dépôt       |
| `GITHUB_TOKEN`        | —                    | uniquement pour un dépôt privé         |
| `DETECTION_LECTURE_SECONDES` | `60`          | mise à jour rapide après un épisode terminé (`0` = off) |
| `TMDB_API_KEY`        | —                    | clé TMDB pour les affiches             |
| `TMDB_LANGUE`         | `fr`                 | langue préférée des affiches           |
| `MEDIATHEQUE`         | `true`               | entrée « Jellyverse » dans Mes médias et le menu |

Elles ont la priorité sur `/mnt/docker/jellyverse/data/config.yml`.

## Bon à savoir

- L'ordre numéroté est dans la **description** de la fiche ; les affiches à
  l'intérieur suivent le tri de Jellyfin.
- La progression affichée est celle de `JELLYFIN_USER`. Pour un autre profil,
  duplique le service dans `docker-compose.yml` avec un autre `JELLYFIN_USER`
  et un autre `PREFIXE_COLLECTION`.
- La description est verrouillée pour que Jellyfin ne l'écrase pas.
- Compatible Jellyfin 10.9 → 12.1. L'authentification utilise l'en-tête
  `Authorization: MediaBrowser Token="…"`, le seul encore accepté par Jellyfin 12
  (les anciens `X-Emby-Token` / `?api_key=` y sont désactivés).
- Depuis Jellyfin 12, la page d'une série affiche les collections auxquelles elle
  appartient : la fiche de l'univers est donc accessible directement depuis la série.
