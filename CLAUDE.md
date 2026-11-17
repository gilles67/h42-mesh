# CLAUDE.md — h42-mesh

Ce fichier donne à Claude Code le contexte du projet. Il est lu à chaque session.
La référence complète de l'architecture est `docs/architecture.md` : en cas de doute, s'y reporter.

## Le projet

h42-mesh (h42 pour Home42) est un VPN maillé auto-hébergé qui relie plusieurs sites (maisons) en un réseau routé dynamiquement.

- Chaque site a un ou deux routeurs Debian (x86_64 ou arm64).
- Chaque routeur a une ou plusieurs connexions internet (fibre, 4G, 5G, Starlink…).
- Deux VPS (Debian 13, IPv4 et IPv6 publiques, datacenters distincts) hébergent le contrôleur et servent de relais.
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
| `agent/` | Python, pyroute2, Jinja2, service systemd ; pilote WireGuard, FRR, keepalived |
| `gui/` | TypeScript, React, Vite, Mantine, TanStack Query, React Flow, client généré depuis OpenAPI |

Déploiement VPS : conteneurs Podman lancés par Quadlet (Traefik, contrôleur, interface) ; WireGuard, FRR et l'agent tournent sur l'hôte.

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

### Authentification et sécurité
- Les clés privées (WireGuard X25519 et signature Ed25519) sont **générées sur le routeur et ne le quittent jamais**. Les deux paires de clés sont distinctes.
- Enrôlement : jeton à usage unique, généré par l'utilisateur, stocké sous forme d'empreinte, à durée limitée, lié au routeur déclaré. Le routeur envoie sa clé publique Ed25519 avec le jeton.
- Échanges courants : l'agent signe un **JWT de courte durée** (environ 1 minute) avec sa clé Ed25519. Le contrôleur accepte **uniquement EdDSA** et vérifie `iss`, `sub`, `aud`, `exp` et `jti` (anti-rejeu).
- Pas de filtrage par adresse IP (pas d'ipAllowList) : la sécurité repose sur l'authentification.
- Utilisateurs de l'interface : session par cookie sécurisé, double authentification TOTP, limitation des tentatives.

### Modèle de connexion internet
Chaque connexion porte :
- `role` : `active` ou `backup` (secours ; une connexion de secours a **toujours** une priorité moindre) — valeurs en anglais dans le code et l'API, l'interface traduit ;
- `priority` : optionnelle, départage un même rôle ;
- connexion directe possible : oui/non, **séparément pour IPv4 et IPv6** ;
- plage de ports IPv4 : optionnelle (IPv4 partagées) ;
- facturée au volume : optionnel ;
- type : informatif uniquement (ne pilote aucun comportement).

Établissement d'un tunnel direct : possible dès qu'**un seul** côté accepte les connexions entrantes (l'autre initie, keepalive WireGuard 25 s). IPv6 d'abord, puis IPv4, sinon relais par les VPS. Une seule famille d'adresses par paire de connexions.

### Routage BGP (FRR)
- Un AS privé sur 4 octets par site : `4200000001`, `4200000002`… ; VPS : `4200000101` et `4200000102`.
- eBGP sur chaque tunnel, iBGP entre les deux routeurs d'un même site. Identifiant de routeur : adresse en `10.254.0.0/24`. Adresses de tunnels en `10.255.0.0/16`.
- Un tunnel prend le rôle le plus faible de ses deux extrémités. Ordre de préférence :
  1. direct, active ↔ active ;
  2. via VPS, sur connexions actives ;
  3. direct, impliquant une connexion de secours ;
  4. via VPS, impliquant une connexion de secours.
- Les routes reçues par un tunnel de secours portent une **communauté BGP large « secours »** (par exemple `4200000101:1:2`) ; toute route qui la porte reçoit une préférence locale basse.
- BFD rapide sur les tunnels actifs ; temporisations lentes sans BFD sur les tunnels de secours et les connexions facturées au volume.
- Seuls les réseaux locaux déclarés exportés sont annoncés.

## Conventions de nommage

| Élément | Nom |
| --- | --- |
| Paquets Python distribués | `h42-mesh-controller`, `h42-mesh-agent` |
| Nom d'import Python | `h42mesh` |
| Service de l'agent | `h42-mesh-agent.service` |
| Conteneurs | `h42-mesh-controller`, `h42-mesh-gui` |
| Commande d'enrôlement | `h42-mesh-agent enroll --controller … --token …` |

## Style de code

- **Code en anglais** : identifiants, commentaires, docstrings, messages d'erreur et de journal, noms et données de test. La documentation (`docs/`) et les réponses restent en français.

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

# agent : à définir
# interface : à définir
```
