# Jellyfin Univers (Docker)

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
jellyverse/
├── docker-compose.yml     ← réglages de connexion
├── Dockerfile
├── jellyfin_univers.py
├── web/univers.js         ← bouton + panneau injectés dans Jellyfin
├── requirements.txt
└── data/                  ← monté dans le conteneur (/data)
    ├── config.yml
    └── univers/
        ├── mushishi.yml   ← un fichier = une fiche
        └── _modele.yml.exemple
```

## Installation

1. Dans Jellyfin : **Tableau de bord → Clés API → +**, copie la clé.
2. Dans `docker-compose.yml`, renseigne `JELLYFIN_URL`, `JELLYFIN_API_KEY`
   et `JELLYFIN_USER`.
   - Jellyfin sur la même machine mais dans un autre compose : décommente la
     partie `networks` (nom du réseau visible avec `docker network ls`) et
     utilise `http://jellyfin:8096`.
   - Sinon, mets l'IP du serveur : `http://192.168.1.10:8096`.
3. Vérifie tes fichiers sans rien modifier :
   ```bash
   docker compose run --rm jellyverse --test
   ```
4. Lance l'application :
   ```bash
   docker build -t tropicfront/jellyverse .
   docker compose up -d
   docker compose logs -f
   ```

Le conteneur tourne en continu. Il met à jour les fiches toutes les
`INTERVALLE_MINUTES` minutes, et **immédiatement** dès que tu ajoutes, modifies
ou supprimes un `.yml` dans `data/univers/` (vérifié toutes les 10 secondes).

## Bouton dans l'interface Jellyfin

L'application ajoute dans l'interface web de Jellyfin :

- un **bouton flottant 🌌** en bas à droite, qui s'allume en bleu quand la page
  affichée (série, saison, épisode, film ou collection) fait partie d'un univers ;
- un **bouton « hub »** à côté de Lecture / Favori sur la page de détail ;
- un **panneau** avec l'ordre, la progression, l'étape en cours et un bouton
  « Ouvrir » qui mène directement au prochain épisode ou film à regarder.
  Sans univers sur la page, le bouton flottant liste tous tes univers.

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
Pour vérifier, ouvre `http://IP:8099/api/univers` dans ton navigateur.

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
- Le bouton à côté de Lecture / Favori dépend de la mise en page de la page de
  détail ; si Jellyfin la change, le bouton flottant 🌌 reste disponible.

## Ajouter un univers

Crée un fichier `.yml` dans `data/univers/` (voir `mushishi.yml` et
`_modele.yml.exemple`). Rien à redémarrer.

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

Elles ont la priorité sur `data/config.yml`.

## Bon à savoir

- L'ordre numéroté est dans la **description** de la fiche ; les affiches à
  l'intérieur suivent le tri de Jellyfin.
- La progression affichée est celle de `JELLYFIN_USER`. Pour un autre profil,
  duplique le service dans `docker-compose.yml` avec un autre `JELLYFIN_USER`
  et un autre `PREFIXE_COLLECTION`.
- La description est verrouillée pour que Jellyfin ne l'écrase pas.
- Supprimer un `.yml` ne supprime pas la collection : efface-la dans Jellyfin.
- Compatible Jellyfin 10.9 → 12.1. L'authentification utilise l'en-tête
  `Authorization: MediaBrowser Token="…"`, le seul encore accepté par Jellyfin 12
  (les anciens `X-Emby-Token` / `?api_key=` y sont désactivés).
- Depuis Jellyfin 12, la page d'une série affiche les collections auxquelles elle
  appartient : la fiche de l'univers est donc accessible directement depuis la série.
