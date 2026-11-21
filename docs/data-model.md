# h42-mesh — modèle de données du contrôleur

> **Statut : brouillon à valider.** Ce document découle des décisions de `architecture.md`, qui reste la référence en cas de désaccord. Les points encore à trancher sont listés à la fin.

Le contrôleur stocke ses données avec Tortoise ORM (SQLite ou PostgreSQL). Les noms d'entités et de champs sont ceux du code, donc en anglais ; les explications sont en français.

## Conventions communes

- **Identifiant** : chaque entité a un identifiant `id` de type UUID. C'est cet identifiant (l'« UID ») que l'agent utilise, par exemple pour désigner une connexion dans la requête de reconnaissance des adresses publiques.
- **Dates** : `created_at` et `updated_at` sur chaque entité, en UTC avec fuseau horaire.
- **Adresses IP et réseaux** : stockés en texte, validés avec `ipaddress` et Pydantic.
- **Secrets** : les champs marqués « chiffré » (PSK, secret TOTP) sont des objets JSON (champ JSON de Tortoise) qui contiennent le secret chiffré et ce qu'il faut pour le déchiffrer, sel compris : `{"v": 1, "kdf": "scrypt", "salt": "…", "nonce": "…", "ciphertext": "…"}`. Ils sont chiffrés avec une clé dérivée de la phrase secrète du contrôleur et de ce sel (voir « Secrets stockés par le contrôleur » dans `architecture.md`).
- **Valeurs énumérées** : stockées en texte, en anglais (`active`, `backup`…) ; l'interface les traduit.
- **Unicité par maillage** : quand une valeur doit être unique dans un maillage, l'entité porte une référence directe au maillage (`mesh`), même si elle s'en déduit (tunnel → connexion → routeur → site → maillage), pour que la contrainte d'unicité soit portée par la base. Le contrôleur vérifie que cette référence est cohérente.
- **Valeurs calculées, non stockées** : rôle d'un tunnel, communauté « secours » ; elles se déduisent des données stockées à chaque calcul de configuration. Le nom des interfaces de tunnel et la plage de ports d'un routeur dépendent du numéro de maillage, local à l'agent : c'est l'agent qui les calcule.

## Vue d'ensemble

```
User ──< MeshAccess >── Mesh ──< Site ──< Router ──< Connection
                          │                  │             │   │
                          │                  │             └─┬─┘
                          │                  │            Tunnel (deux connexions)
                          │                  ├──< EnrollmentToken
                          │                  └──< BgpRoute (→ Tunnel facultatif)
                          └── (créé par) User
```

`A ──< B` : un A a plusieurs B.

## Utilisateurs et droits

### `User` — utilisateur de l'interface

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `username` | texte | unique | Identifiant de connexion |
| `password_hash` | texte | | Empreinte du mot de passe (Argon2) |
| `must_change_password` | booléen | défaut vrai | Changement obligatoire à la première connexion |
| `totp_secret` | JSON, chiffré | facultatif | Secret de la double authentification |
| `totp_last_step` | entier | facultatif | Numéro de la dernière fenêtre TOTP (30 s) acceptée : un code ne peut pas être rejoué |
| `is_admin` | booléen | défaut faux | Administrateur ; **un seul compte** l'a, créé à l'installation |
| `can_create_meshes` | booléen | défaut faux | Droit de créer des maillages, donné par l'administrateur |
| `failed_login_count` | entier | défaut 0 | Limitation des tentatives |
| `locked_until` | date | facultatif | Blocage temporaire après trop d'échecs |
| `last_login_at` | date | facultatif | |

L'unicité de l'administrateur est vérifiée par le contrôleur (une contrainte « un seul vrai » n'est pas portable entre SQLite et PostgreSQL sans SQL écrit à la main).

### `MeshAccess` — accès d'un utilisateur à un maillage

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `user` | → `User` | | |
| `mesh` | → `Mesh` | | |
| `level` | `manage` / `read` | | Gestion ou lecture seule |

Unicité : (`user`, `mesh`). L'administrateur n'a pas besoin de ligne ici : il accède à tout.

### `UserSession` — session de l'interface

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `user` | → `User` | | |
| `token_hash` | texte | unique | Empreinte du jeton porté par le cookie |
| `stage` | `totp_pending` / `authenticated` | | `totp_pending` : mot de passe vérifié, code TOTP attendu (session de quelques minutes, qui n'ouvre que l'envoi du code) ; `authenticated` : session complète, avec un nouveau jeton |
| `expires_at` | date | | |
| `last_seen_at` | date | | Expiration après inactivité |

## Maillage et inventaire

### `Mesh` — maillage

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `name` | texte | unique | |
| `created_by` | → `User` | facultatif | Créateur, qui reçoit l'accès en gestion |

### `Site`

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `mesh` | → `Mesh` | | |
| `name` | texte | unique dans le maillage | Par exemple « Hub Home42 » |
| `nickname` | texte, `^[a-z0-9]{4}$` | unique dans le maillage | Quadrigramme, par exemple `root`, `pari` ; utilisé dans le nom des interfaces de tunnel |
| `location` | texte, 64 caractères au plus | facultatif | Emplacement du site, informatif |
| `asn` | entier, 4200000000–4294967294 | unique dans le maillage | AS privé du site, défini par l'utilisateur |

Il n'y a pas de type de site : un site de VPS est un site comme les autres.

### `Router`

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `site` | → `Site` | | |
| `number` | entier 0–1 | unique dans le site | `r0`, `r1` |
| `name` | texte | | Nom libre |
| `signing_public_key` | texte (44 caractères) | facultatif, unique | Clé publique Ed25519 de l'agent ; remplacée lors d'un renouvellement, sans historique |
| `signing_key_revoked` | booléen | défaut faux | Révocation : le routeur est refusé à la requête suivante |
| `enrolled_at` | date | facultatif | |
| `last_seen_at` | date | facultatif | Dernier contact de l'agent |
| `routes_reported_at` | date | facultatif | Date du dernier relevé de la table BGP (voir `BgpRoute`) ; si elle est trop ancienne, l'état affiché n'est plus à jour |

### `Connection` — connexion internet d'un routeur

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `router` | → `Router` | | |
| `number` | entier 0–9 | unique sur le routeur | `c0` à `c9` |
| `name` | texte | | Nom libre |
| `role` | `active` / `backup` | | Précédence de routage |
| `priority` | entier | facultatif | Départage un même rôle |
| `direct` | `none` / `ipv4` / `ipv6` / `both` | défaut `none` | Familles dans lesquelles la connexion accepte les connexions entrantes |
| `description` | texte | facultatif | Description libre |
| `isp` | texte | facultatif | Opérateur, déduit de l'adresse publique par la base GeoLite2 ASN de MaxMind (IPv4 si connue, sinon IPv6) |
| `public_ipv4` | texte | facultatif | Adresse IPv4 publique |
| `public_ipv4_updated_at` | date | facultatif | |
| `public_ipv6` | texte | facultatif | Adresse IPv6 publique (stable) |
| `public_ipv6_updated_at` | date | facultatif | |

Ne sont **pas** dans le contrôleur, mais dans la configuration locale de l'agent, par connexion : l'interface physique, la plage de ports éventuelle, l'adresse forcée éventuelle, les délais du repli IPv6 → IPv4 (30 s, 10 min par défaut). Le numéro du maillage, la VRF d'un maillage et le lien interne d'un site à deux routeurs (interface et adresse fe80:: de l'autre routeur) sont aussi locaux à l'agent.

## Tunnels

### `Tunnel`

Un tunnel relie deux connexions de routeurs de sites différents, dans un même maillage.

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `mesh` | → `Mesh` | | Pour l'unicité de la paire d'adresses |
| `connection_a` | → `Connection` | | Extrémité qui écoute (si les deux acceptent les entrées : celle du site de plus faible AS) ; première adresse du /31 (IPv4 et IPv6) |
| `connection_b` | → `Connection` | | Extrémité qui établit la communication ; seconde adresse (IPv4 et IPv6) |
| `ipv4_network` | texte, /31 dans 169.254.0.0/16 | unique dans le maillage | Paire d'adresses tirée au hasard |
| `ipv6_network` | texte, /127 dans fe80::/64 | unique dans le maillage | Paire locale au lien déduite de `ipv4_network` : préfixe `fe80::a9fe:` suivi des deux derniers octets IPv4 (par exemple `169.254.12.34/31` → `fe80::a9fe:c22/127`) |
| `public_key_a` | texte (44 caractères) | facultatif | Clé publique WireGuard de `a` pour ce tunnel, remontée par son agent |
| `public_key_b` | texte (44 caractères) | facultatif | Clé publique WireGuard de `b` pour ce tunnel |
| `preshared_key` | JSON, chiffré | | PSK WireGuard du tunnel, générée par le contrôleur à la création du tunnel, transmise uniquement aux agents de `a` et `b` |
| `port_a` | entier | facultatif | Port de `a`, choisi et remonté par son agent ; `b` le contacte |
| `port_b` | entier | facultatif | Port de `b`, choisi et remonté par son agent |

Le tunnel n'est utilisable que lorsque les deux clés publiques et `port_a` sont connus.

Unicité : (`connection_a`, `connection_b`), et une même paire ne peut pas exister dans l'autre sens.

Calculé, non stocké : le rôle (le plus faible des deux connexions), les familles d'adresses possibles (celles dans lesquelles `a` accepte les connexions entrantes).

Calculé par l'agent, inconnu du contrôleur : le nom de l'interface de chaque côté (`wd<maillage>c<locale><quadrigramme distant>r<routeur distant>c<distante>`), qui dépend du numéro de maillage local à l'agent.

### `TunnelStatus` — état remonté par les agents

Une ligne par tunnel et par extrémité.

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `tunnel` | → `Tunnel` | | |
| `router` | → `Router` | | Extrémité qui remonte l'état |
| `family_in_use` | `ipv6` / `ipv4` | facultatif | Famille utilisée après repli éventuel |
| `last_handshake_at` | date | facultatif | Dernière poignée de main WireGuard |
| `bgp_established` | booléen | défaut faux | Session BGP établie |
| `reported_at` | date | | |

Unicité : (`tunnel`, `router`).

## Routes BGP

### `BgpRoute` — routes BGP d'un routeur

Photo de la table BGP de chaque routeur, remontée par son agent. À chaque relevé, le contrôleur remplace toutes les routes du routeur (suppression puis insertion, dans une même transaction) : pas d'historique. Une ligne par chemin connu vers un préfixe, pas seulement le meilleur.

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `router` | → `Router` | | Routeur qui a cette route dans sa table |
| `prefix` | texte, réseau IPv4 ou IPv6 | | Réseau de destination ; la famille d'adresses s'en déduit |
| `source` | `local` / `tunnel` / `internal` | | Annoncé par ce routeur, appris par un tunnel, ou appris de l'autre routeur du site (iBGP) |
| `tunnel` | → `Tunnel` | facultatif | Tunnel d'apprentissage, si `source` vaut `tunnel` ; l'agent envoie l'UID du tunnel, pas le nom de l'interface |
| `as_path` | liste d'entiers (JSON) | | Chemin AS |
| `origin_asn` | entier | facultatif | Dernier AS du chemin, donc le site qui annonce le réseau ; vide pour une route `local` |
| `is_best` | booléen | | Route choisie par BGP |
| `is_backup` | booléen | | Porte la communauté « secours » (`*:1:2`) |
| `local_pref` | entier | facultatif | Préférence locale |

Pas de contrainte d'unicité sur (`router`, `prefix`) : un même préfixe peut être connu par plusieurs chemins. La date du relevé est portée par `Router.routes_reported_at`. Les routes `local` montrent les réseaux réellement exportés par chaque routeur, qui ne sont pas déclarés dans le contrôleur.

## Enrôlement et authentification des agents

### `EnrollmentToken`

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `router` | → `Router` | | Routeur déclaré auquel le jeton est lié |
| `token_hash` | texte | unique | Empreinte SHA-256 du jeton |
| `expires_at` | date | | Quelques heures |
| `used_at` | date | facultatif | Usage unique |
| `created_by` | → `User` | | |

### `UsedJwtId` — anti-rejeu des JWT des agents

| Champ | Type | Contraintes | Rôle |
| --- | --- | --- | --- |
| `router` | → `Router` | | |
| `jti` | texte | unique avec `router` | Identifiant du JWT |
| `expires_at` | date | | Purge des lignes expirées |

Stocké en base plutôt qu'en mémoire, pour fonctionner avec deux instances du contrôleur (étape 6).

## Suppressions

| Suppression | Effet |
| --- | --- |
| Maillage | Refusée tant qu'il contient des sites |
| Site | Refusée tant qu'il contient des routeurs |
| Routeur | Supprime ses connexions, ses tunnels, ses jetons, ses états et ses routes BGP |
| Connexion | Supprime ses tunnels |
| Utilisateur | Supprime ses accès et ses sessions ; l'administrateur ne peut pas être supprimé |

## Points à valider

Aucun pour l'instant. Les sujets reportés sont dans [todo.md](todo.md).
