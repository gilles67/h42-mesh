# Spécification — contrôleur (`controller/`)

> **Statut : brouillon.** Ce fichier détaille, pour le contrôleur, les décisions de [architecture.md](../architecture.md) et le modèle de [data-model.md](../data-model.md), qui restent la référence. Ce qui n'y figure pas encore est marqué *proposition*.

## Rôle

API seule (sans interface intégrée) qui :

- garde l'inventaire des maillages, sites, routeurs et connexions ;
- décide des tunnels, attribue leurs paires d'adresses 169.254 et génère leurs PSK ;
- distribue à chaque agent sa configuration ;
- enregistre ce que les agents remontent : adresses publiques, clés publiques et ports des tunnels, état des tunnels, routes BGP ;
- gère les utilisateurs de l'interface et leurs droits.

Il ne fait jamais passer de trafic. S'il est injoignable, les tunnels et le routage existants continuent de fonctionner.

## Technologies

Python, FastAPI, Pydantic, Tortoise ORM ; SQLite (PostgreSQL possible, même code). Conteneur Podman derrière Traefik.

## Configuration (variables d'environnement)

| Variable | Rôle |
| --- | --- |
| `H42_MESH_DATABASE_URL` | Adresse de la base (SQLite ou PostgreSQL) |
| `H42_MESH_PASSPHRASE_FILE` | Fichier contenant la phrase secrète de chiffrement des secrets en base (secret Podman) |
| `H42_MESH_GEOLITE2_ASN_FILE` | Base GeoLite2 ASN de MaxMind ; facultative (sans elle, `isp` reste vide) |
| `H42_MESH_TRUSTED_PROXIES` | Réseaux de confiance autorisés à transmettre `X-Forwarded-For` (Traefik), en JSON, par exemple `["10.89.0.0/24"]` ; vide par défaut |

Réglages des sessions de l'interface, avec leur valeur par défaut :

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `H42_MESH_SESSION_LIFETIME_MINUTES` | 720 (12 h) | Durée totale d'une session |
| `H42_MESH_SESSION_IDLE_MINUTES` | 30 | Expiration après inactivité |
| `H42_MESH_PENDING_LOGIN_MINUTES` | 5 | Délai pour saisir le code TOTP après le mot de passe |
| `H42_MESH_SESSION_COOKIE_SECURE` | `true` | Cookie réservé à HTTPS ; `false` seulement en développement local en HTTP |
| `H42_MESH_MAX_FAILED_LOGINS` | 5 | Échecs consécutifs (mot de passe ou code TOTP) avant blocage |
| `H42_MESH_LOCKOUT_MINUTES` | 15 | Durée du blocage |

Réglages de l'enrôlement et des JWT des agents :

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `H42_MESH_ENROLLMENT_TOKEN_HOURS` | 4 | Durée de validité d'un jeton d'enrôlement ; créer un jeton supprime les jetons non utilisés du même routeur |
| `H42_MESH_AGENT_JWT_AUDIENCE` | `h42-mesh-controller` | Valeur attendue de `aud` |
| `H42_MESH_AGENT_JWT_MAX_LIFETIME_SECONDS` | 300 | `exp` refusé s'il est plus loin dans le futur |
| `H42_MESH_AGENT_JWT_LEEWAY_SECONDS` | 30 | Tolérance d'horloge sur `exp` |

Authentification d'un agent : `Authorization: Bearer <JWT>`, EdDSA uniquement (en-tête vérifié avant tout décodage), `iss` = `sub` = UID du routeur, `aud`, `exp` et `jti` obligatoires, `jti` enregistré (128 caractères au plus) et purgé après expiration. Toute erreur donne 401 `invalid_agent_token` sans détail (la raison est journalisée) ; un routeur révoqué reçoit 403 `router_revoked`, seulement après vérification de sa signature. Un nouvel enrôlement remplace la clé et lève la révocation.

## Démarrage

1. Lecture de la phrase secrète (s'arrête avec un message clair si le fichier est absent, illisible ou vide).
2. Application des migrations.
3. Si la base contient déjà des secrets, essai de déchiffrement de l'un d'eux (s'arrête avec un message clair si la phrase secrète est fausse). Cette vérification suit les migrations, car sur une base neuve les tables n'existent pas encore ; les migrations ne touchent jamais aux secrets.
4. Si la base ne contient aucun utilisateur : création de l'administrateur, mot de passe aléatoire affiché une seule fois dans le journal.

## API

Deux familles d'appels, avec deux authentifications distinctes. *Proposition* : préfixe `/api/v1`.

### API de l'interface (utilisateurs)

Session par cookie sécurisé, double authentification TOTP, limitation des tentatives. Chaque appel vérifie les droits : administrateur, ou accès `manage` / `read` au maillage concerné.

| Ressource | Opérations | Droit requis |
| --- | --- | --- |
| Session | connexion (mot de passe puis TOTP), déconnexion, changement de mot de passe, enregistrement TOTP | — |
| Utilisateurs | lister, créer, modifier, supprimer, donner le droit de créer des maillages | administrateur |
| Maillages | lister (ceux auxquels l'utilisateur a accès), créer, renommer, supprimer | création : administrateur ou droit de créer |
| Accès à un maillage | lister, accorder, retirer (`manage` / `read`) | `manage` sur le maillage |
| Sites, routeurs, connexions | lister, lire, créer, modifier, supprimer | lecture : `read` ; modification : `manage` |
| Jetons d'enrôlement | créer (affiché une seule fois) | `manage` |
| Révocation d'un routeur | révoquer la clé de signature | `manage` |
| Tunnels | lister, lire (calculés par le contrôleur, pas créés à la main) | `read` |
| État | état des tunnels, routes BGP par routeur, date du dernier contact | `read` |

### API des agents

Chaque appel est authentifié par un JWT de courte durée signé par l'agent (EdDSA uniquement ; `iss`, `sub`, `aud`, `exp`, `jti` vérifiés ; `jti` enregistré contre le rejeu). Seul l'enrôlement utilise le jeton à usage unique.

| Appel | Route | Contenu |
| --- | --- | --- |
| Enrôlement | `POST /agent/enroll` | jeton d'enrôlement + clé publique Ed25519 ; réponse : identifiant du routeur |
| Identité | `GET /agent/me` | routeur, maillage, quadrigramme, numéro |
| Renouvellement de la clé de signature | `PUT /agent/signing-key` | nouvelle clé publique, requête signée avec l'ancienne ; remplace l'ancienne |
| Reconnaissance des adresses publiques | `POST /agent/public-address` | UID de la connexion (du routeur authentifié), famille, adresse forcée facultative ; le contrôleur enregistre l'adresse vue (ou forcée) et met à jour l'opérateur |
| Lecture de la configuration | `GET /agent/config` | la configuration voulue du routeur (voir ci-dessous) ; `ETag`, et 304 avec `If-None-Match` |
| Remontée des tunnels | `POST /agent/tunnels` | pour chaque tunnel : clé publique WireGuard de son extrémité, port choisi ; tout ou rien, un port une seule fois par routeur |
| Remontée de l'état | `PUT /agent/tunnel-status` | par tunnel : famille utilisée, dernière poignée de main, session BGP établie ; photo complète, remplace l'état précédent du routeur |
| Remontée des routes BGP | `PUT /agent/bgp-routes` | table BGP complète du routeur ; remplace la précédente (10 000 routes au plus) |

Un agent ne peut désigner que ses propres connexions et tunnels : ceux d'un autre routeur sont traités comme inconnus (404).

**Adresse vue** : adresse du pair TCP ; l'en-tête `X-Forwarded-For` n'est lu que si ce pair est dans `H42_MESH_TRUSTED_PROXIES` (Traefik), de droite à gauche en sautant les adresses de confiance. Une adresse vue non publique (privée, locale au lien, bouclage…) est refusée ; une adresse forcée ne l'est pas. L'opérateur est déduit de l'IPv4 si elle est connue, sinon de l'IPv6.

**Configuration d'un routeur** (format 1) : maillage ; site (quadrigramme, AS) ; routeur (numéro, nom) ; connexions (UID, numéro, rôle, priorité, `direct`, adresses publiques), triées par numéro ; tunnels du routeur, triés par UID, chacun avec : UID, côté (`a` ou `b`), rôle, familles possibles, connexion locale, paires IPv4 et IPv6 avec les adresses locale et distante déjà calculées, clé publique et port déjà enregistrés pour cette extrémité, PSK, et l'autre extrémité (connexion, quadrigramme, AS, numéros de routeur et de connexion, clé publique). Seul le côté `b` reçoit le port de `a` et ses adresses publiques (`endpoints`, dans les familles où `a` accepte les entrées, IPv6 d'abord). Le nom des interfaces, la plage de ports et les communautés BGP sont calculés par l'agent. L'empreinte (`fingerprint`, aussi `ETag`) est le SHA-256 du JSON canonique, sans l'empreinte elle-même.

La PSK n'est transmise qu'aux agents des deux extrémités du tunnel, jamais par l'API de l'interface.

## Calcul des tunnels

À chaque changement d'inventaire, de `direct`, de rôle ou d'adresse publique :

1. Pour chaque paire de connexions de deux sites différents du même maillage : retenir la paire si elle n'est pas secours ↔ secours et si au moins une des deux accepte les connexions entrantes.
2. Choisir `a` : la connexion qui accepte les entrées ; si les deux les acceptent, celle du site de plus faible AS.
3. Créer les tunnels nouveaux (tirage de la paire 169.254 avec nouvelle tentative en cas de conflit, calcul de la paire IPv6 qui en découle, génération de la PSK) ; supprimer ceux qui ne sont plus retenus ; si `a` et `b` s'inversent, réattribuer adresses et ports : les deux extrémités échangent leur place sur le même tunnel, chaque connexion gardant sa clé publique et son port, la paire d'adresses et la PSK restant les mêmes (le nouveau `a` prend la première adresse de chaque paire).

Ce calcul est une fonction pure (inventaire en entrée, liste de tunnels voulus en sortie), testée indépendamment de la base. Quand les deux connexions acceptent les entrées, même dans des familles différentes, `a` est celle du site de plus faible AS ; le tunnel n'utilise que les familles de `a`.

Déclenchement : à chaque création, modification ou suppression d'une connexion, modification d'un site (AS) et suppression d'un routeur, dans la requête elle-même. L'application est idempotente et sans transaction globale (une erreur d'unicité annulerait toute la transaction sous PostgreSQL) : une exécution interrompue est terminée par la suivante.

## Tests

pytest, sur SQLite et PostgreSQL. Cas prioritaires : calcul des tunnels, droits par maillage, vérification des JWT (algorithme, expiration, rejeu), unicité par maillage avec nouvelle tentative, chiffrement des secrets.

## Points ouverts

- Format exact de la configuration envoyée à l'agent et de son empreinte.
- Fréquence des remontées d'état et de routes, et délai au-delà duquel un routeur est affiché comme injoignable.
- Paramètres de la dérivation lente (scrypt ou Argon2, coût) : à fixer à l'implémentation, et enregistrés dans chaque objet JSON.
