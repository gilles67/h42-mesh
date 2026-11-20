# CLAUDE.md — h42-mesh

Ce fichier donne à Claude Code le contexte du projet. Il est lu à chaque session.
La référence complète de l'architecture est `docs/architecture.md` : en cas de doute, s'y reporter.
Chaque composant a sa spécification : `docs/specs/controller.md`, `docs/specs/agent.md`, `docs/specs/gui.md`.
Le modèle de données du contrôleur est décrit dans `docs/data-model.md` : les modèles Tortoise doivent le suivre.

## Le projet

h42-mesh (h42 pour Home42) est un VPN maillé auto-hébergé qui relie plusieurs sites (maisons) en un réseau routé dynamiquement.

- Chaque site a un ou deux routeurs Debian (x86_64 ou arm64).
- Chaque routeur a une ou plusieurs connexions internet (fibre, 4G, 5G, Starlink…).
- Deux VPS (Debian 13, IPv4 et IPv6 publiques, datacenters distincts) hébergent le contrôleur ; grâce à leurs adresses publiques, ils servent naturellement de relais.
- Première cible : 5 sites. Licence : MIT.

Hors périmètre : les zones réseau (VLAN), l'adressage des réseaux locaux et le pare-feu entre zones relèvent d'une **application pare-feu séparée**. Ne pas les implémenter ici.

## Structure du dépôt

```
controller/   API du contrôleur (Python)
agent/        Agent des routeurs et des VPS (Python)
gui/          Interface web (TypeScript)
docs/         Documentation (architecture.md)
```

## Composants et technologies

| Composant | Technologies |
| --- | --- |
| `controller/` | Python, FastAPI, Pydantic, Tortoise ORM, SQLite (PostgreSQL possible) |
| `agent/` | Python, Pydantic (validation de la configuration locale), pyroute2, Jinja2, service systemd ; pilote wireguard-go (un processus par tunnel), FRR, keepalived |
| `gui/` | TypeScript, React, Vite, Mantine, TanStack Query, React Flow, client généré depuis OpenAPI |

Déploiement VPS : conteneurs Podman lancés par Quadlet (Traefik, contrôleur, interface) ; wireguard-go, FRR et l'agent tournent sur l'hôte.

## Règles d'architecture (à respecter impérativement)

### Contrôleur
- Le contrôleur est une **API seule**, sans interface intégrée. Il configure le réseau mais ne fait jamais passer le trafic.
- Sa description **OpenAPI est le contrat** avec l'interface et l'application pare-feu : schémas Pydantic **écrits explicitement**, distincts des modèles Tortoise. Ne jamais exposer directement un modèle de base.
- La base est choisie par une seule variable de configuration (adresse de la base). Le code doit fonctionner **à l'identique sur SQLite et PostgreSQL** :
  - pas de SQL brut ;
  - adresses IP et réseaux stockés en texte, validés avec `ipaddress` et Pydantic ;
  - dates en UTC avec fuseau horaire ;
  - attribution d'adresses et d'AS protégée par des contraintes d'unicité, avec nouvelle tentative en cas de conflit (pas de verrouillage de lignes).
- Migrations générées à partir des modèles (outil de migration de Tortoise ORM).

### Agent
- **Idempotent** : appliquer deux fois la même configuration ne change rien. Il compare l'état voulu à l'état réel et n'applique que les différences.
- Il ne réimplémente pas ce que font WireGuard, FRR et keepalived : il génère leur configuration et les pilote.
- Il connaît les deux adresses du contrôleur et bascule si la première ne répond pas.
- Si le contrôleur est injoignable, les tunnels et le routage existants continuent de fonctionner.

### Configuration locale de l'agent
- Hors du contrôleur, dans le fichier de configuration de l'agent : par maillage, les adresses des contrôleurs, le **numéro du maillage** et la **VRF** facultative ; pour un site à deux routeurs, le **lien interne** (interface et adresse fe80:: de l'autre routeur) ; par connexion (désignée par son UID), l'**interface physique** (obligatoire), l'adresse forcée éventuelle et les délais du repli IPv6 → IPv4. La passerelle est relevée par l'agent sur l'interface, pas déclarée.

- **Échanges agent → contrôleur** depuis la VRF d'une connexion internet (émis par l'instance de la connexion ; connexions actives d'abord par priorité, puis secours), avec un **client DNS intégré à l'agent** qui résout le nom des contrôleurs dans cette VRF, jamais la résolution du système (serveurs par défaut : `1.1.1.1`, `2606:4700:4700::1111`, `8.8.8.8`, `2001:4860:4860::8888`, modifiables dans la configuration de l'agent) ; certificat TLS vérifié pour le nom du contrôleur.

- **Pas de paquet commun** entre l'agent et le contrôleur : l'agent a sa propre copie des modèles Pydantic des messages, adaptée à ses besoins ; la description OpenAPI du contrôleur reste la référence. Réponses du contrôleur lues avec `extra="ignore"` ; configuration locale avec `extra="forbid"`.

- **Configuration stockée localement** par l'agent (`state_dir`, droits `0600`) : dernière configuration valide et la précédente, état local de chaque tunnel (clé privée, port) ; écriture atomique (fichier temporaire puis renommage) ; appliquée au démarrage avant tout contact avec le contrôleur ; récupération par interrogation régulière avec empreinte (`If-None-Match`, réponse 304). Détails dans `docs/specs/agent.md`.

### Authentification et sécurité
- Les clés privées (WireGuard X25519 et signature Ed25519) sont **générées sur le routeur et ne le quittent jamais**. Les deux paires de clés sont distinctes.
- Enrôlement : jeton à usage unique, généré par l'utilisateur, stocké sous forme d'empreinte, à durée limitée, lié au routeur déclaré. Le routeur envoie sa clé publique Ed25519 avec le jeton.
- Échanges courants : l'agent signe un **JWT de courte durée** (environ 1 minute) avec sa clé Ed25519. Le contrôleur accepte **uniquement EdDSA** et vérifie `iss`, `sub`, `aud`, `exp` et `jti` (anti-rejeu).
- Pas de filtrage par adresse IP (pas d'ipAllowList) : la sécurité repose sur l'authentification.
- Utilisateurs de l'interface : session par cookie sécurisé, double authentification TOTP, limitation des tentatives.
- **Secrets en base** (PSK, secrets TOTP) chiffrés avec une clé dérivée d'une **phrase secrète lue dans un fichier** dont le chemin est donné par une variable d'environnement (`H42_MESH_PASSPHRASE_FILE`, secret Podman sur le VPS) ; jamais de secret dans le code, l'image ou le dépôt. Chaque secret est stocké dans un **objet JSON** qui contient aussi son sel de dérivation, son nonce et la méthode utilisée (`v`, `kdf`, `salt`, `nonce`, `ciphertext`) ; clés dérivées gardées en mémoire.
- **Administrateur** généré à l'installation du contrôleur (premier démarrage sans utilisateur : mot de passe aléatoire affiché une fois dans le journal, changement et TOTP obligatoires à la première connexion) ; compte unique, il crée les autres utilisateurs et est le **seul** à accéder à tous les maillages. Les autres utilisateurs ne voient que les maillages qui leur sont attribués, avec un accès par maillage en **gestion** ou en **lecture seule** (toutes les informations du maillage, sans modification). Un gestionnaire accorde ou retire ces accès pour les maillages qu'il gère. Un utilisateur peut recevoir le droit de **créer des maillages** ; il gère alors ceux qu'il crée.

### Modèle de connexion internet
Chaque connexion porte :
- `role` : `active` ou `backup` (secours ; une connexion de secours a **toujours** une priorité moindre) — valeurs en anglais dans le code et l'API, l'interface traduit ;
- `priority` : optionnelle, départage un même rôle ;
- connexion directe possible (`direct`) : `none` / `ipv4` / `ipv6` / `both` ;
- opérateur (`isp`) : déduit par le contrôleur de l'adresse publique (base GeoLite2 ASN de MaxMind, fichier donné par `H42_MESH_GEOLITE2_ASN_FILE`, attribution MaxMind obligatoire) ;
- description : texte libre, informatif.

La plage de ports d'une connexion (`ports`, valable en IPv4 et en IPv6) est dans la configuration locale de l'agent, pas dans le contrôleur. Connexions facturées au volume : à redéfinir (`docs/todo.md`), ne pas implémenter.

Adresses publiques : **au plus une IPv4 et une IPv6 par connexion**, jamais saisies dans le contrôleur. Pour chaque connexion et chaque famille, l'agent envoie une requête authentifiée de reconnaissance contenant l'**UID de la connexion**, en sortant par cette connexion ; le contrôleur enregistre l'adresse source vue (en-tête de Traefik accepté uniquement s'il vient de Traefik ; en IPv6, adresse stable, jamais temporaire). **Adresse forcée** : si la configuration locale de la connexion dans l'agent fixe l'adresse, la requête la contient et le contrôleur l'enregistre à la place de l'adresse vue (cas d'une machine à la fois routeur et contrôleur) ; il vérifie que la connexion appartient au routeur authentifié et la famille de l'adresse.

Établissement d'un tunnel direct : possible dès qu'**un seul** côté accepte les connexions entrantes (l'autre initie, keepalive WireGuard 25 s). IPv6 d'abord, puis IPv4, sinon relais par un autre site. Une seule famille à la fois par tunnel. **Repli automatique** : le côté qui initie reçoit les deux adresses ; sans poignée de main WireGuard en IPv6 dans le délai, l'agent bascule seul en IPv4, le signale au contrôleur, et retente l'IPv6 périodiquement. Délais par défaut : 30 s de repli, 10 min entre deux tentatives IPv6 ; modifiables **par connexion dans la configuration de l'agent** (pas dans le contrôleur).

### Maillages
- Un contrôleur pilote **un ou plusieurs maillages (`Mesh`) indépendants** : maillage → sites → routeurs → connexions ; un tunnel relie deux connexions d'un même maillage, jamais deux maillages.
- **Numéro de maillage géré par l'agent** (pas par le contrôleur) : 0 à 9, défini dans la configuration locale de l'agent pour chaque maillage de la machine, unique sur la machine. Quadrigrammes, AS et paires d'adresses de tunnel sont uniques **par maillage** (contraintes d'unicité incluant le maillage).
- **Un VPS est un routeur comme les autres**, pas un type de site : il est déclaré dans un site créé par l'utilisateur (ici « Hub Home42 », quadrigramme `root`, routeurs `r0` et `r1`). Un VPS peut être routeur, contrôleur, ou les deux ; un maillage peut n'avoir aucun VPS routeur.
- **Pas de rôle de relais** : tout routeur peut relayer, selon les connexions dont il dispose ; **BGP choisit librement** le chemin (pas d'allongement du chemin AS, pas d'exclusion de connexion du transit).
- **Pour l'instant, un agent ne rejoint qu'un maillage, sur un seul contrôleur** (numéro de maillage 0 par défaut). Le multi-maillage (VRF par maillage supplémentaire) et le multi-contrôleur sont décrits dans `docs/todo.md` : **ne pas les implémenter**, mais ne pas les rendre impossibles (garder le numéro de maillage dans le nom des interfaces et le calcul des plages de ports).
- Un utilisateur ne voit et ne gère que les maillages qui lui sont attribués.

### Tunnels
- Un tunnel relie **deux connexions internet** de deux routeurs **de sites différents** (pas deux routeurs) ; deux routeurs peuvent donc être reliés par plusieurs tunnels. Jamais de tunnel de l'application entre deux routeurs d'un même site.
- Extrémités : par convention **`a` écoute, `b` établit la communication** (si les deux acceptent les entrées, `a` est la connexion du site de plus faible AS) ; `a` prend la première adresse de chaque paire, `b` la seconde. Paire IPv6 **locale au lien, propre au tunnel, déduite de la paire IPv4** (`ipv6_network`) : préfixe `fe80::a9fe:` + deux derniers octets, ex. `169.254.12.34/31` → `fe80::a9fe:c22/127`.
- **Clés par tunnel** : une paire de clés WireGuard par extrémité, générée par l'agent (clé privée jamais transmise, deux clés publiques stockées), et une **PSK** WireGuard par tunnel, **générée par le contrôleur** à la création du tunnel (format `wg genpsk` : 32 octets aléatoires en base64), stockée chiffrée et transmise uniquement aux deux agents concernés.
- **Une interface WireGuard par tunnel, avec un seul pair**, dont les `AllowedIPs` sont `0.0.0.0/0` et `::/0`. WireGuard n'installe aucune route : c'est BGP qui choisit le tunnel.
- Paires retenues : active ↔ active et secours ↔ active ; **jamais secours ↔ secours**. Et toujours : au moins un côté accepte les connexions entrantes (champ `direct`).
- Tunnels enregistrés par le contrôleur (adresses, ports remontés par l'agent, noms d'interface stables).
- Ports : **un port fixe par extrémité**, choisi par l'agent de chaque côté dans la plage de son routeur, `42000 + 2000 × maillage + 1000 × numéro du routeur` (42000 : constante de l'agent ; intersection avec la plage de ports de la connexion déclarée dans la configuration locale de l'agent, le cas échéant) ; le contrôleur stocke les deux ports et transmet celui de `a` à `b` ; un tunnel garde ses ports. Un port n'est utilisable qu'une fois par routeur. L'agent réserve sa plage (`net.ipv4.ip_local_reserved_ports`).
- **wireguard-go**, pas le module du noyau : un processus par tunnel, lancé dans la **VRF de sa connexion internet** (`ip vrf exec`) ; l'interface de tunnel reste dans la VRF par défaut. Les interfaces des connexions internet sont **toujours** dans une VRF dédiée, jamais dans la VRF par défaut ; ces VRF sont **créées par la configuration du système**, pas par l'agent, qui lit leur nom dans sa configuration locale et vérifie seulement qu'elles existent. `rp_filter` souple sur les interfaces de tunnel.
- **Une instance de l'agent par connexion internet**, lancée dans la VRF de la connexion (`ip vrf exec`), qui gère en sous-processus les wireguard-go de ses tunnels ; un processus principal dans la VRF par défaut (FRR, keepalived, système, `status`). Détails dans `docs/specs/agent.md`.
- **Gestion de WireGuard isolée dans un module dédié** de l'agent (créer, mettre à jour, supprimer, lire l'état, lister les tunnels) : le reste de l'agent ne dépend que de cette interface, jamais directement de wireguard-go, pour pouvoir changer d'implémentation (voir `docs/specs/agent.md`).

### Routage BGP (FRR)
- Un AS privé sur 4 octets par site (hub des VPS compris), **défini par l'utilisateur** ; le contrôleur vérifie seulement qu'il est unique dans le maillage et dans la plage 4200000000–4294967294. Pas de numérotation automatique ni de tranche réservée aux VPS.
- eBGP sur chaque tunnel (**une seule session, sur la paire IPv6 locale au lien du tunnel, avec `extended-nexthop`**, routes IPv4 et IPv6), iBGP entre les deux routeurs d'un même site, par le lien interne du site (réseau local d'une maison ; pour un site de deux VPS, tunnel monté par l'administrateur hors de l'application), avec `next-hop-self`. Pas de VRRP sur un site de VPS.
- Session iBGP sur les adresses IPv6 **locales au lien** du lien interne, **entièrement configurée dans l'agent** (nom de l'interface et adresse fe80:: de l'autre routeur, dans la configuration locale ; rien dans le contrôleur) ; voisin déclaré explicitement, pas de *BGP unnumbered*. Une seule session pour IPv4 et IPv6 (`extended-nexthop`, RFC 8950).
- Un tunnel prend le rôle le plus faible de ses deux extrémités. Ordre de préférence :
  1. direct, active ↔ active ;
  2. relayé par un autre site (en pratique le hub), sur connexions actives ;
  3. direct, impliquant une connexion de secours ;
  4. relayé par un autre site, impliquant une connexion de secours.
- Les routes reçues par un tunnel de secours portent une **communauté BGP large « secours »** `<AS du site>:1:2`, posée à la réception par le routeur qui reçoit la route ; toute route qui porte une communauté `*:1:2` (expression régulière `^[0-9]+:1:2$`, quel que soit l'AS) reçoit une préférence locale basse.
- BFD rapide sur les tunnels actifs ; temporisations lentes sans BFD sur les tunnels de secours.
- **Pas d'identifiant BGP (router-id) attribué** : FRR le choisit lui-même ; collisions possibles entre voisins (point d'attention dans `docs/architecture.md`).
- Annonces (première version) : FRR annonce les **réseaux connectés de la VRF par défaut** (`redistribute connected`), avec un *route-map* généré par l'agent qui **exclut** les interfaces de tunnel (`wd…`, 169.254.0.0/16, fe80::/10), la boucle locale et les interfaces de conteneurs. Rien n'est déclaré dans le contrôleur ; l'échange avec l'application pare-feu est reporté (`docs/todo.md`). L'agent remonte la table BGP de FRR (toutes les routes, entité `BgpRoute`), que le contrôleur remplace à chaque relevé, **sans historique**. Aucune adresse propre au routeur n'est annoncée : le diagnostic depuis un routeur se fait avec son adresse du réseau local comme source (`ping -I`).

## Conventions de nommage

| Élément | Nom |
| --- | --- |
| Paquets Python distribués | `h42-mesh-controller`, `h42-mesh-agent` |
| Nom d'import Python | `h42mesh` |
| Service de l'agent | `h42-mesh-agent.service` |
| Conteneurs | `h42-mesh-controller`, `h42-mesh-gui` |
| Commande d'enrôlement | `h42-mesh-agent enroll --controller … --token …` |
| État de l'agent | `h42-mesh-agent status` (obligatoire) ; `h42-mesh-agent` sans commande affiche la même chose ; l'unité systemd lance `h42-mesh-agent run` |
| Connexions locales de l'agent | `h42-mesh-agent connection list/show/set/remove c0 …` (interface, VRF, plage de ports, adresses forcées, délais du repli) |
| Quadrigramme de site | 4 caractères `[a-z0-9]`, unique dans le mesh (VPS compris) |
| Numéro de routeur / de connexion | `r0`–`r1` (unique dans le site) / `c0`–`c9` (unique sur le routeur) |
| Interface de tunnel | `wd<mesh>c<conn. locale><quadrigramme distant>r<routeur distant>c<conn. distante>`, ex. `wd0c0parir0c0` |

## Style de code

- **Code en anglais**, sans exception :
  - identifiants (variables, fonctions, classes, modules, types TypeScript, composants React) ;
  - modèles Tortoise, tables, colonnes et valeurs énumérées ;
  - routes, paramètres et champs JSON de l'API, codes et messages d'erreur ;
  - clés de configuration et variables d'environnement ;
  - commentaires, docstrings, messages de journal, noms et données de test ;
  - messages de commit.
- La documentation (`docs/`) et les réponses restent en français.
- **Interface en anglais**, traduisible plus tard : tous les textes affichés passent par le mécanisme de traduction (i18n, clés de traduction, anglais comme seule langue fournie pour l'instant) ; jamais de texte en dur dans les composants, y compris pour afficher les valeurs de l'API.

### Python
- Annotations de type partout ; code asynchrone côté contrôleur.
- Formatage et analyse : ruff ; vérification de types : mypy ; tests : pytest.
- Tests du contrôleur exécutés sur **SQLite et PostgreSQL**.
- Dépendances : uniquement des bibliothèques compatibles avec la licence MIT (MIT, BSD, Apache 2.0). Les outils GPL (FRR, WireGuard, keepalived) sont pilotés comme programmes séparés, jamais intégrés.

### TypeScript
- Mode strict activé.
- Le client API est **généré** depuis la description OpenAPI du contrôleur, jamais écrit à la main.
- Le mainteneur débute en TypeScript : **expliquer brièvement chaque fichier créé ou modifié** côté `gui/`, et privilégier un code simple et lisible.

## Façon de travailler

- Avancer **une petite tâche à la fois**, en suivant la feuille de route de `docs/architecture.md`.
- Écrire ou mettre à jour les tests avec chaque changement, et les lancer avant de conclure.
- **Ne jamais modifier une décision d'architecture de ce fichier sans le demander d'abord.** Si une règle semble poser problème, l'expliquer et proposer une alternative.
- Répondre en français.

## Commandes

À compléter au fur et à mesure (installation, tests, lancement local) :

```
# contrôleur (depuis controller/)
uv sync                                    # installation
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run tortoise makemigrations -n <nom>    # après toute modification des modèles
uv run tortoise migrate                    # base choisie par H42_MESH_DATABASE_URL
uv run python -m h42mesh.controller.openapi          # exporte ../openapi/controller.json (après tout changement de l'API)
uv run python -m h42mesh.controller.openapi --check  # vérifie que le fichier est à jour

# lancement local du contrôleur (depuis controller/) : phrase secrète de développement, jamais versionnée
# migrations appliquées au démarrage ; base SQLite h42-mesh.db par défaut
printf 'dev passphrase' > .dev-passphrase
H42_MESH_PASSPHRASE_FILE=.dev-passphrase uv run uvicorn h42mesh.controller.app:create_app --factory --reload
# PowerShell : $env:H42_MESH_PASSPHRASE_FILE = ".dev-passphrase" ; puis la commande uvicorn
# santé : http://127.0.0.1:8000/api/v1/health ; documentation : http://127.0.0.1:8000/api/v1/docs

# agent : à définir
# interface : à définir
```
