# Prompts pour Claude Code

> Ce fichier n'est **pas** une spécification : il contient les demandes à copier dans Claude Code, dans l'ordre. Les références restent `CLAUDE.md`, `docs/architecture.md`, `docs/data-model.md` et `docs/specs/`.

## Façon de procéder

- Une session Claude Code par prompt, dans l'ordre. Chaque prompt est une petite tâche.
- Pour les prompts marqués **[plan]**, Claude Code doit d'abord proposer un plan et attendre ta validation avant de coder (mode plan : `Shift+Tab` deux fois, ou demande-le simplement).
- Après chaque prompt : relire les changements, vérifier que les tests passent, puis faire un commit avant de passer au suivant.
- Si Claude Code signale qu'une règle de l'architecture pose problème, reviens en discuter dans le projet de conception avant de modifier les documents.

## 0. Avant de commencer (à faire toi-même)

1. Supprimer `docs/specs/agent-1.md` (ancienne copie de `agent.md`).
2. Faire un commit de la documentation (`CLAUDE.md`, `docs/`).

---

## Contrôleur

### C1. Modèles de données [plan]

```text
Lis CLAUDE.md, docs/architecture.md et docs/data-model.md.

Les modèles Tortoise actuels du contrôleur (controller/src/h42mesh/controller/models/) ne correspondent plus à docs/data-model.md. Réécris-les pour qu'ils suivent exactement ce document : User, MeshAccess, UserSession, Mesh, Site, Router, Connection, Tunnel, TunnelStatus, BgpRoute, EnrollmentToken, UsedJwtId, avec leurs champs, valeurs par défaut, contraintes d'unicité (y compris par maillage) et règles de suppression.

- Aucune base n'est en production : supprime la migration existante et régénère une migration initiale avec l'outil de migration de Tortoise.
- Les champs « chiffré » (Tunnel.preshared_key, User.totp_secret) sont des champs JSON ; leur chiffrement sera fait dans une tâche suivante, ne l'implémente pas ici.
- Pas d'API dans cette tâche, seulement les modèles, les validateurs et la migration.
- Mets à jour les tests (SQLite) : création de chaque entité, contraintes d'unicité, suppressions en cascade et suppressions refusées.

Montre-moi d'abord ton plan (fichiers, modèles, points d'interprétation de data-model.md) et attends ma validation. À la fin, lance ruff, mypy et pytest.
```

### C2. Chiffrement des secrets

```text
Lis CLAUDE.md et la section « Secrets stockés par le contrôleur » de docs/architecture.md.

Implémente dans le contrôleur le chiffrement des secrets en base :
- lecture de la phrase secrète dans le fichier indiqué par H42_MESH_PASSPHRASE_FILE (réglages Pydantic existants) ;
- chiffrement d'un secret en objet JSON {"v", "kdf", "salt", "nonce", "ciphertext"} : dérivation scrypt avec un sel propre à chaque secret, chiffrement authentifié AES-GCM ou ChaCha20-Poly1305 (bibliothèque cryptography), valeurs en base64 ;
- cache en mémoire des clés dérivées ;
- fonction de vérification au démarrage : si la base contient au moins un secret, essayer de le déchiffrer et lever une erreur claire si la phrase secrète est fausse.

Expose deux fonctions simples (chiffrer une chaîne, déchiffrer un objet JSON) utilisées plus tard pour Tunnel.preshared_key et User.totp_secret. Tests : aller-retour, phrase secrète fausse, objet altéré, sel différent pour deux chiffrements du même secret. Lance ruff, mypy et pytest.
```

### C3. Squelette de l'API

```text
Lis CLAUDE.md et docs/specs/controller.md.

Crée l'application FastAPI du contrôleur :
- préfixe /api/v1, initialisation de Tortoise au démarrage, vérification de la phrase secrète (tâche précédente) au démarrage ;
- une route de santé (GET /api/v1/health) ;
- un script ou une commande qui exporte la description OpenAPI dans openapi/controller.json à la racine du dépôt (ce fichier sera utilisé par l'interface et par les tests de l'agent) ;
- commande de lancement locale documentée dans la section « Commandes » de CLAUDE.md.

Rappel : schémas Pydantic écrits explicitement, distincts des modèles Tortoise. Tests avec le client de test de FastAPI. Lance ruff, mypy et pytest.
```

### C4. Utilisateurs, sessions et administrateur [plan]

```text
Lis CLAUDE.md, la section « Utilisateurs et droits » de docs/architecture.md, docs/data-model.md et l'API de l'interface dans docs/specs/controller.md.

Implémente :
- au démarrage, si la base ne contient aucun utilisateur, création de l'administrateur avec un mot de passe aléatoire affiché une seule fois dans le journal (must_change_password = vrai) ;
- connexion en deux étapes (mot de passe Argon2, puis code TOTP), session par cookie sécurisé (UserSession, jeton stocké sous forme d'empreinte), expiration, déconnexion ;
- changement de mot de passe obligatoire et enregistrement du TOTP à la première connexion ; secret TOTP chiffré avec le module de la tâche C2 ;
- limitation des tentatives (failed_login_count, locked_until) ;
- gestion des utilisateurs par l'administrateur (lister, créer, modifier, supprimer, droit de créer des maillages) ; l'administrateur ne peut pas être supprimé.

Montre-moi d'abord ton plan (routes, schémas, dépendances FastAPI de vérification de session et de droits). Tests complets du parcours de connexion. Lance ruff, mypy et pytest.
```

### C5. Maillages, sites, routeurs, connexions [plan]

```text
Lis CLAUDE.md, docs/data-model.md et docs/specs/controller.md.

Implémente l'API de l'interface pour Mesh, MeshAccess, Site, Router et Connection, avec les droits : administrateur sur tout ; sinon accès `manage` ou `read` par maillage ; création de maillage réservée à l'administrateur et aux utilisateurs qui en ont le droit (le créateur reçoit l'accès `manage`) ; un gestionnaire accorde et retire les accès de son maillage.

Validations : quadrigramme (nickname) ^[a-z0-9]{4}$ unique dans le maillage, AS dans 4200000000–4294967294 unique dans le maillage, numéro de routeur 0–1 unique dans le site, numéro de connexion 0–9 unique sur le routeur, `direct` dans none/ipv4/ipv6/both. Règles de suppression de data-model.md. Ne calcule pas encore les tunnels.

Montre-moi d'abord ton plan (routes, schémas, organisation des vérifications de droits). Tests des droits pour chaque rôle. Régénère openapi/controller.json. Lance ruff, mypy et pytest.
```

### C6. Calcul des tunnels [plan]

```text
Lis CLAUDE.md, les sections « Tunnels » et « Modèle de connexion et précédence » de docs/architecture.md, et « Calcul des tunnels » de docs/specs/controller.md.

Implémente le calcul des tunnels :
- une fonction pure (sans base) qui, à partir de l'inventaire d'un maillage, donne la liste des tunnels voulus : paires de connexions de sites différents, jamais secours ↔ secours, au moins un côté qui accepte les entrées (`direct`), choix de `a` (celle qui accepte les entrées ; si les deux, celle du site de plus faible AS) ;
- l'application en base : création des nouveaux tunnels (paire 169.254 /31 tirée au hasard hors 169.254.0.0/24, 169.254.169.0/24 et 169.254.255.0/24, nouvelle tentative en cas de conflit ; paire IPv6 déduite : fe80::a9fe: + deux derniers octets, /127 ; PSK de 32 octets aléatoires en base64, chiffrée), suppression des tunnels qui ne sont plus voulus, réattribution si `a` et `b` s'inversent ;
- déclenchement après chaque modification d'inventaire, de `direct`, de rôle ou d'AS.

Montre-moi d'abord ton plan. Tests nombreux sur la fonction pure (cas des 4 combinaisons actif/secours, des 4 valeurs de `direct`, choix de `a`), et tests de l'unicité des paires. Lance ruff, mypy et pytest.
```

### C7. Enrôlement et authentification des agents [plan]

```text
Lis CLAUDE.md et la section « Authentification et sécurité » de docs/architecture.md.

Implémente :
- création d'un jeton d'enrôlement par un gestionnaire du maillage (jeton long et aléatoire, affiché une seule fois, empreinte SHA-256 stockée, valable quelques heures, lié au routeur) ;
- enrôlement : jeton + clé publique Ed25519 ; jeton invalidé après usage ;
- authentification des appels des agents par JWT signé EdDSA uniquement (tout autre algorithme refusé, y compris none) : vérification de iss, sub, aud, exp et jti, enregistrement du jti dans UsedJwtId contre le rejeu, purge des entrées expirées ;
- révocation (signing_key_revoked) et renouvellement de la clé (nouvelle clé signée avec l'ancienne, remplacement sans historique).

Montre-moi d'abord ton plan. Tests de sécurité : mauvais algorithme, JWT expiré, rejoué, mauvaise audience, routeur révoqué, jeton déjà utilisé ou expiré. Lance ruff, mypy et pytest.
```

### C8. API des agents [plan]

```text
Lis CLAUDE.md, docs/specs/controller.md (« API des agents ») et docs/specs/agent.md (« Récupération et stockage de la configuration »).

Implémente les appels des agents, authentifiés par la tâche C7 :
- lecture de la configuration du routeur, avec empreinte (ETag) et réponse 304 si l'agent envoie la même empreinte (If-None-Match) ; la PSK n'est envoyée qu'aux deux extrémités du tunnel ;
- reconnaissance des adresses publiques : UID de la connexion (qui doit appartenir au routeur authentifié), adresse forcée facultative, sinon adresse source vue ; l'en-tête de Traefik n'est accepté que s'il vient de Traefik (réglage des adresses de confiance) ; mise à jour de `isp` avec la base GeoLite2 ASN si H42_MESH_GEOLITE2_ASN_FILE est défini (bibliothèque maxminddb) ;
- remontée des tunnels : clé publique et port de chaque extrémité ;
- remontée de l'état des tunnels (TunnelStatus) et de la table BGP (BgpRoute remplacée en bloc, Router.routes_reported_at).

Montre-moi d'abord ton plan, en particulier le format de la configuration envoyée. Tests de chaque appel, dont l'isolation entre routeurs. Régénère openapi/controller.json. Lance ruff, mypy et pytest.
```

### C9. Déploiement sur un VPS

```text
Lis CLAUDE.md et la section « Déploiement sur les VPS » de docs/architecture.md.

Prépare le déploiement du contrôleur (pas encore de l'interface) : Containerfile du contrôleur, unités Quadlet pour Traefik et le contrôleur, configuration de Traefik par fichier (/api vers le contrôleur, Let's Encrypt, socket Podman non exposé), secret Podman pour la phrase secrète, volume pour la base SQLite et pour la base GeoLite2. Range ces fichiers dans un dossier deploy/ et documente l'installation pas à pas dans deploy/README.md (en français). Ne traite pas encore la question ouverte des services dans la VRF de la connexion : signale-la dans le README.
```

---

## Agent

### A1. Squelette et configuration locale [plan]

```text
Lis CLAUDE.md et docs/specs/agent.md.

Crée le paquet de l'agent dans agent/ (nom distribué h42-mesh-agent, import h42mesh.agent), avec la même organisation d'outils que le contrôleur (uv, ruff, mypy strict, pytest) :
- les modèles Pydantic de la configuration locale (AgentConfig, InternalLink, ConnectionSettings, PortRange) exactement comme dans « Validation par Pydantic », avec extra="forbid" ;
- la lecture de /etc/h42-mesh/agent.toml (chemin modifiable) ;
- la ligne de commande avec les commandes enroll, run, status, connection (vides pour l'instant, sauf la validation de la configuration) ; sans commande, l'agent se comporte comme status.

Montre-moi d'abord ton plan (organisation des modules). Tests de validation statique : fichier valide, champ inconnu, doublons, bornes. Lance ruff, mypy et pytest.
```

### A2. Stockage local et modèles des messages

```text
Lis CLAUDE.md et docs/specs/agent.md (« Récupération et stockage de la configuration », « Échanges avec le contrôleur »).

Implémente dans l'agent :
- les modèles Pydantic des messages échangés avec le contrôleur (copie propre à l'agent, extra="ignore" pour les réponses), d'après openapi/controller.json ;
- le stockage dans state_dir : config.json, config.previous.json, tunnels/<uid>.json, agent.key ; écriture atomique (fichier temporaire, fsync, renommage), droits 0600 ;
- un test qui vérifie la compatibilité des modèles de l'agent avec openapi/controller.json.

Pas encore d'appel réseau. Lance ruff, mypy et pytest.
```

### A3. Organisation en processus et échanges réseau [plan]

```text
Lis CLAUDE.md et docs/specs/agent.md (« Organisation en processus », « Échanges avec le contrôleur »).

Implémente :
- le processus principal qui lance une instance par connexion avec `ip vrf exec <vrf> h42-mesh-agent connection-worker <uid>`, la surveille et la relance ; communication par socket Unix locale ;
- dans l'instance : client DNS intégré (dnspython, serveurs de la configuration), client HTTPS vers l'adresse résolue avec vérification du certificat pour le nom du contrôleur, bascule vers le second contrôleur ;
- le choix de l'instance pour joindre le contrôleur : connexions actives par priorité, puis secours ;
- la commande enroll et la signature des JWT (EdDSA, durée d'une minute environ, jti unique) ;
- la récupération périodique de la configuration (If-None-Match, 304), sa validation et son stockage, et la reconnaissance des adresses publiques par chaque instance.

Montre-moi d'abord ton plan. Ce qui touche aux VRF ne peut être testé que sous Linux avec les droits root : sépare la logique (testée normalement) de l'exécution système (testée à part, marquée comme test d'intégration). Lance ruff, mypy et pytest.
```

### A4. Gestion de WireGuard [plan]

```text
Lis CLAUDE.md et docs/specs/agent.md (« Isolation de la gestion de WireGuard », « Boucle principale »).

Implémente le module de gestion de WireGuard derrière une interface (Protocol ou classe abstraite) : créer, mettre à jour, supprimer un tunnel, lire son état, lister les tunnels. Première implémentation : wireguard-go, un sous-processus par tunnel lancé par l'instance de la connexion, configuré avec wg (programme séparé), interface wd<maillage>c<locale><quadrigramme>r<routeur>c<distante>, AllowedIPs 0.0.0.0/0 et ::/0, PSK, keepalive 25 s côté b, adresses IPv4 et IPv6 du tunnel, repli IPv6 → IPv4 côté b selon les délais de la connexion, surveillance et relance du processus. Le reste de l'agent ne doit dépendre que de l'interface.

Montre-moi d'abord ton plan. Fournis une implémentation factice de l'interface pour les tests de la boucle. Lance ruff, mypy et pytest.
```

### A5. FRR, keepalived et réglages système

```text
Lis CLAUDE.md et la section « Routage BGP » de docs/architecture.md.

Implémente dans le processus principal la génération (Jinja2) de la configuration de FRR : une session eBGP par tunnel sur sa paire IPv6 locale au lien avec extended-nexthop, BFD sur les tunnels actifs et temporisations lentes sur les tunnels de secours, communauté « secours » <AS du site>:1:2 posée à la réception sur les tunnels de secours et reconnue par ^[0-9]+:1:2$ avec préférence locale basse, redistribute connected dans la VRF par défaut avec le route-map d'exclusion, session iBGP sur le lien interne avec next-hop-self. Rechargement de FRR seulement si la configuration a changé. Génération de keepalived pour un site de maison à deux routeurs. Réglages système : rp_filter souple sur les tunnels, net.ipv4.ip_local_reserved_ports pour la plage du routeur.

Tests par comparaison de fichiers générés pour des cas types (tunnel actif, tunnel de secours, site à deux routeurs). Lance ruff, mypy et pytest.
```

### A6. Commandes status et connection

```text
Lis CLAUDE.md et docs/specs/agent.md (« Commande status », « Commande connection »).

Implémente :
- l'écriture de /run/h42-mesh/status.json par la boucle, et la commande status (et sans commande) : identité, agent, contrôleur, connexions, tunnels, lien interne ; option --json ; code de retour non nul en cas de problème ; message clair si le service est arrêté ;
- la commande connection list/show/set/remove : connexion désignée par son numéro (c0) ou son UID, vérifications avant écriture (interface, VRF, rattachement, plage de ports), modification du fichier avec tomlkit en conservant les commentaires, prise en compte par le service sans redémarrage ;
- la remontée de l'état des tunnels et de la table BGP (vtysh … json) au contrôleur.

Lance ruff, mypy et pytest.
```

---

## Interface

### G1. Squelette de l'interface [plan]

```text
Lis CLAUDE.md et docs/specs/gui.md. Je débute en TypeScript et en React : explique brièvement chaque fichier que tu crées.

Crée l'application dans gui/ : Vite, React, TypeScript en mode strict, Mantine, TanStack Query, react-i18next (anglais seulement pour l'instant, tous les textes par des clés), client API généré depuis openapi/controller.json (propose l'outil de génération, sous licence compatible MIT), mention MaxMind en pied de page. Ajoute les commandes (installation, lancement, génération du client, vérification des types, tests) dans la section « Commandes » de CLAUDE.md.

Montre-moi d'abord ton plan (outils, structure des dossiers).
```

### G2. Connexion et première connexion

```text
Lis CLAUDE.md et docs/specs/gui.md. Explique brièvement chaque fichier créé ou modifié.

Implémente l'écran de connexion (mot de passe puis code TOTP), le changement de mot de passe et l'enregistrement du TOTP à la première connexion (affichage du QR code), la déconnexion, et la redirection vers la connexion quand la session a expiré.
```

### G3. Inventaire d'un maillage

```text
Lis CLAUDE.md et docs/specs/gui.md. Explique brièvement chaque fichier créé ou modifié.

Implémente les écrans Maillages, Sites et routeurs, Connexions et Enrôlement (jeton affiché une seule fois, avec la commande h42-mesh-agent enroll à copier). Les boutons de modification n'apparaissent qu'avec l'accès manage.
```

Les écrans suivants (topologie, tunnels, routes BGP, accès, utilisateurs) seront demandés une fois ces bases en place.
