# h42-mesh — architecture du VPN maillé multi-sites

Nov 17, 2026 · @Gilles

Cinq maisons reliées en VPN maillé WireGuard, routées en BGP avec FRR (un AS par site), pilotées par un contrôleur et des agents en Python sur Debian, avec deux VPS comme contrôleurs et relais. Les connexions actives sont toujours préférées aux connexions de secours. Les zones, l'adressage des réseaux locaux et le pare-feu relèvent d'une application complémentaire.

## Les composants

L'application relie plusieurs maisons en VPN maillé : un contrôleur distribue la configuration, et les routeurs de chaque site montent des tunnels directs entre eux. Chaque site compte un ou deux routeurs, chacun avec une ou plusieurs connexions internet.

&#91;embedded content: architecture · contrôleur, 3 maisons, tunnels maillés\]

Exemple à trois maisons : chaque routeur reçoit sa configuration du contrôleur, puis le trafic circule directement entre les sites.

1. **Le contrôleur** : API seule, en Python (FastAPI, Pydantic, Tortoise ORM ; SQLite, PostgreSQL possible), sans interface intégrée, en principal sur le VPS 1 et en secours sur le VPS 2, base répliquée de l'un vers l'autre. Il garde l'inventaire des sites, routeurs et connexions, attribue les adresses des routeurs et des tunnels ainsi que les numéros d'AS, et distribue la configuration. Il échange avec l'application pare-feu par API, et publie automatiquement sa description OpenAPI.
2. **L'agent** : service systemd en Python sur chaque routeur Debian (x86 ou arm64). Il récupère sa configuration auprès du contrôleur (dont il connaît les deux adresses), applique les différences de façon idempotente avec pyroute2, génère les configurations de FRR et keepalived (Jinja2), et remonte l'état des liens.
3. **Le plan de données** : WireGuard dans le noyau Linux. Les clés privées sont générées sur le routeur et ne le quittent jamais ; seule la clé publique remonte au contrôleur.
4. **Les deux VPS en relais** : chaque routeur garde un tunnel vers chacun d'eux, et les VPS sont reliés entre eux. Ils servent de chemin de secours, de passage pour les liens en CGNAT et de point de découverte des adresses publiques des maisons.
5. **L'interface graphique** : composant séparé, simple client de l'API du contrôleur. Application web monopage en TypeScript (React, Vite, Mantine, TanStack Query, React Flow pour la topologie), compilée en fichiers statiques : aucun serveur Node.js en production. Son client API est généré depuis la description OpenAPI du contrôleur, ce qui garde les modèles Pydantic comme seule source de vérité.

Principe clé : si le contrôleur tombe, les tunnels déjà établis continuent de fonctionner. Il configure, il ne fait pas passer le trafic.

## Difficultés techniques et réponses retenues

Chaque difficulté identifiée a désormais une réponse arrêtée ; le détail du routage et de l'adressage suit dans les sections dédiées.

| Difficulté | Enjeu | Réponse retenue |
| --- | --- | --- |
| Multi-WAN | Chaque tunnel doit sortir par la bonne connexion, sans exploser le nombre de tunnels | Tunnel direct dès qu'un côté accepte les connexions entrantes, relais par les VPS sinon ; routage par politique (*policy routing*) |
| Détection de panne et bascule | Savoir quel lien est vivant et choisir le meilleur chemin | BGP avec FRR ; BFD rapide sur les tunnels actifs, temporisations lentes sur les tunnels de secours |
| Deux routeurs par site | Une seule passerelle visible pour les appareils de la maison | VRRP avec keepalived, qui suit l'état de la connexion active ; iBGP entre les deux routeurs |
| NAT et CGNAT | 4G, 5G et Starlink sont souvent en CGNAT pour l'IPv4 | Paramètre « connexion directe possible » par famille d'adresses, IPv6 privilégiée, relais par les VPS sinon |
| Plan d'adressage | Les réseaux des box se chevauchent souvent (192.168.1.0/24) | Adressage des réseaux locaux défini dans l'application pare-feu ; ce projet n'attribue que les adresses des routeurs et des tunnels |

## Routage BGP

Chaque site a son propre AS privé, et chaque VPS le sien ; un chemin direct traverse donc moins d'AS qu'un chemin relayé et est naturellement préféré.

| Équipement | AS (4 octets, privé) |
| --- | --- |
| Sites 1 à 5 | 4200000001 à 4200000005 |
| VPS 1 | 4200000101 |
| VPS 2 | 4200000102 |

Les numéros sont pris dans la plage privée sur 4 octets, de 4200000000 à 4294967294 (RFC 6996), écrits en notation décimale simple (asplain) dans FRR. Les derniers chiffres reprennent le numéro du site (jusqu'à 100 sites), et la tranche à partir de 4200000101 est réservée aux VPS.

- **Entre sites et vers les VPS** : une session eBGP par tunnel WireGuard ; deux tunnels entre deux routeurs portent deux sessions.
- **Entre les deux routeurs d'un site** : session iBGP (même AS).
- **Identifiant de routeur** : l'adresse d'identité en 10.254.0.x.
- **Annonces** : seuls les réseaux locaux déclarés exportés sont annoncés ; un réseau non exporté n'est jamais connu des autres sites.
- **Cas limite** : si les deux routeurs d'un site perdent le lien entre eux, la protection anti-boucle de BGP les empêche de se joindre via le VPN. Une option FRR existe pour le contourner, à n'utiliser qu'avec prudence.

## Modèle de connexion et précédence

Une connexion de secours a toujours une priorité moindre qu'une connexion active. Le comportement de chaque connexion est déclaré dans le contrôleur, pas déduit de son type.

| Attribut | Valeurs | Rôle |
| --- | --- | --- |
| Rôle | active / secours | Précédence de routage, toujours respectée |
| Priorité | nombre, optionnel | Départage les connexions d'un même rôle |
| Connexion directe possible | oui / non, pour l'IPv4 et pour l'IPv6 | La connexion peut-elle recevoir des tunnels ? |
| Plage de ports IPv4 | optionnelle | Ports d'écoute WireGuard sur une IPv4 partagée |
| Facturée au volume | oui / non, optionnel | Réduit les sondes et limite les tunnels directs |
| Type | fibre, 4G, 5G, Starlink… | Informatif |

Les adresses ne sont pas saisies : l'agent découvre ses adresses IPv6 et son IPv4 publique (vue par les VPS) et les remonte au contrôleur.

### Établissement d'un tunnel direct

Un tunnel direct est possible dès qu'un seul des deux côtés accepte les connexions entrantes ; l'autre côté l'initie et le maintient par un *keepalive* WireGuard toutes les 25 secondes.

1. **IPv6 d'abord**, si les deux côtés l'ont et qu'au moins un l'accepte en entrée.
2. **Sinon IPv4**, si au moins un côté l'accepte en entrée.
3. **Sinon, relais via les VPS**, joignables en IPv4 et en IPv6.

Un tunnel WireGuard n'a qu'une adresse de destination à la fois : le contrôleur choisit une seule famille par paire de connexions.

### Ordre de préférence des chemins

Un tunnel prend le rôle le plus faible de ses deux extrémités.

1. Direct, active ↔ active
2. Via VPS, sur connexions actives
3. Direct, impliquant une connexion de secours
4. Via VPS, impliquant une connexion de secours

Toute route reçue par un tunnel de secours porte une communauté BGP large « secours » (par exemple 4200000101:1:2), qui la suit dans tout le réseau ; chaque routeur donne une préférence locale basse aux routes qui la portent. Sans cela, un chemin via VPS paraîtrait actif alors que le VPS atteint la destination par une connexion de secours.

### Détection de panne

| Tunnel | Détection |
| --- | --- |
| Actif | BFD rapide, bascule en moins d'une seconde |
| Secours | Temporisations BGP lentes, sans BFD |
| Sur connexion facturée au volume | Comme le secours, et tunnels directs limités aux sites qui en ont besoin |

Sur un site à deux routeurs, celui qui porte la connexion active est la passerelle VRRP principale.

## Authentification et sécurité

Chaque routeur prouve son identité avec une clé de signature qu'il est seul à posséder ; l'accès au contrôleur ne dépend pas de l'adresse d'origine, et aucun filtrage par IP n'est utilisé.

### Enrôlement d'un routeur

1. Dans l'interface, l'utilisateur déclare le routeur (site, nom) et génère un jeton à usage unique.
2. Sur le routeur, il lance l'enrôlement de l'agent avec l'adresse du contrôleur et le jeton.
3. L'agent génère sa paire de clés de signature Ed25519 et envoie sa clé publique avec le jeton.
4. Le contrôleur vérifie le jeton, l'invalide et associe la clé publique au routeur.

### Échanges courants

À chaque échange, l'agent signe un JWT de courte durée (une minute environ) avec sa clé privée ; le contrôleur le vérifie avec la clé publique enregistrée (principe de l'assertion signée, RFC 7523).

- **Algorithme** : EdDSA uniquement, imposé côté contrôleur ; tout autre algorithme, dont none, est rejeté.
- **Contenu du JWT** : identifiant du routeur (iss, sub), destinataire (aud), expiration courte (exp), identifiant unique contre le rejeu (jti).
- **Heure** : NTP sur tous les routeurs, avec une tolérance de quelques secondes.
- **Jeton d'enrôlement** : long et aléatoire, stocké sous forme d'empreinte, valable quelques heures, lié au routeur déclaré, affiché une seule fois.
- **Révocation** : désactiver la clé publique d'un routeur le coupe à la requête suivante.
- **Renouvellement** : une nouvelle clé publique signée avec l'ancienne, sans nouvel enrôlement.

### Autres mesures

- **Clés distinctes** : la clé de signature Ed25519 est séparée de la clé WireGuard (X25519), et aucune clé privée ne quitte le routeur.
- **Utilisateurs de l'interface** : session par cookie sécurisé, double authentification TOTP et limitation des tentatives de connexion, l'interface et l'API d'administration étant joignables depuis Internet.
- **Relais** : le trafic relayé est déchiffré puis rechiffré sur le VPS, qui le voit en clair. D'où des VPS durcis (mises à jour, SSH par clé uniquement) et des protocoles chiffrés de bout en bout pour les flux sensibles, comme la vidéo.

## Déploiement sur les VPS

Sur chaque VPS, sous Debian 13, l'API, l'interface et le proxy tournent en conteneurs Podman ; le relais tourne sur l'hôte. Un VPS est ainsi un routeur avec le rôle « relais », géré par le même agent que les maisons.

| Élément | Exécution | Remarque |
| --- | --- | --- |
| Traefik | Conteneur | Point d'entrée HTTPS unique, certificats Let's Encrypt automatiques |
| Contrôleur (FastAPI) | Conteneur | Base SQLite dans un volume ; PostgreSQL en conteneur à partir de l'étape 6 |
| Interface (fichiers statiques) | Conteneur léger (nginx ou équivalent) | Traefik route mais ne sert pas de fichiers |
| WireGuard, FRR | Hôte | Manipulent le noyau et les interfaces réseau |
| Agent Python | Hôte | Pilote WireGuard et FRR |

- **Lancement** : Quadlet, qui fait gérer chaque conteneur par systemd (disponible à partir de Podman 4.4, d'où Debian 13).
- **Routage Traefik** : configuration par fichier, versionnée dans le dépôt ; / vers l'interface, /api vers le contrôleur. Le socket Podman n'est pas exposé à Traefik.
- **Nommage** : un nom par VPS (vps1, vps2) pour une validation HTTP simple des certificats ; les agents connaissent les deux adresses.
- **Ports** : un conteneur rootless n'écoute pas sur 80 et 443 sans réglage système ; à prévoir pour Traefik.
- **Dépôt** : un seul dépôt avec les dossiers controller/, agent/ et gui/.

## Base de données du contrôleur

Le contrôleur accède à sa base par Tortoise ORM, asynchrone comme FastAPI : SQLite d'abord, PostgreSQL possible sans changer les modèles, en modifiant une seule variable de configuration (l'adresse de la base).

- **SQLite** : mode WAL activé, clés étrangères appliquées.
- **Migrations** : générées à partir des modèles, sans SQL écrit à la main ; commande de migration intégrée à Tortoise ORM depuis sa version 1.0, Aerich restant l'alternative ([documentation Aerich](https://github.com/tortoise/aerich)).
- **Séparation** : modèles Tortoise pour le stockage, schémas Pydantic écrits explicitement pour l'API, afin que la description OpenAPI (dont dépendent l'interface et l'application pare-feu) ne change pas par accident.
- **Tests** : sur les deux bases, SQLite en mémoire et PostgreSQL en conteneur.

| Sujet | Règle de portabilité |
| --- | --- |
| Adresses IP et réseaux | Stockées en texte, validées avec ipaddress et Pydantic |
| Dates | En UTC, avec fuseau horaire |
| Données structurées | Champ JSON de Tortoise |
| Attribution d'adresses et d'AS | Contraintes d'unicité et nouvelle tentative en cas de conflit (pas de verrouillage de lignes sous SQLite) |
| SQL brut | À éviter |

SQLite sert aux étapes 1 à 5 de la feuille de route. PostgreSQL arrive à l'étape 6, car sa réplication native entre le VPS 1 et le VPS 2 porte la haute disponibilité ; avec SQLite, il faudrait un outil externe comme Litestream ou des copies régulières.

## Conventions de nommage

Le projet s'appelle h42-mesh (h42 pour Home42) ; ce nom se décline partout de la même façon.

| Élément | Nom |
| --- | --- |
| Dépôt | h42-mesh, avec les dossiers controller/, agent/ et gui/ |
| Paquets Python distribués | h42-mesh-controller, h42-mesh-agent |
| Nom d'import Python | h42mesh (pas de tiret dans un nom de module) |
| Service de l'agent | h42-mesh-agent.service |
| Conteneurs | h42-mesh-controller, h42-mesh-gui |
| Commande d'enrôlement | h42-mesh-agent enroll --controller … --token … |

Le projet est publié sous licence MIT. Avant la publication en open source, vérifier que le nom est libre sur GitHub et PyPI.

## Feuille de route

1. **Fondations** : modèle de données et API du contrôleur, enrôlement par jeton à usage unique avec clé Ed25519, authentification des agents par JWT, déploiement Podman et Traefik sur un VPS.
2. **Premier tunnel** : deux routeurs reliés par l'agent à partir de la configuration reçue du contrôleur.
3. **VPS en relais** : tunnels vers les deux VPS et sessions BGP avec FRR.
4. **Maillage et politique des liens** : tunnels directs selon le paramètre de connexion directe, précédence active/secours avec communautés BGP, BFD.
5. **Redondance de site** : deux routeurs avec keepalived et iBGP.
6. **Haute disponibilité du contrôleur** sur le VPS 2 avec PostgreSQL répliqué, puis interface graphique en TypeScript avec double authentification des utilisateurs.

## Projets open source existants

Netbird, Headscale (serveur libre compatible Tailscale) et Nebula couvrent déjà une partie du besoin. Ils visent surtout la connexion d'appareils individuels, pas de sites entiers avec plusieurs connexions et des routeurs redondants : c'est probablement là que se situe la valeur ajoutée du projet. À étudier avant de coder, pour s'appuyer sur l'un d'eux ou s'en inspirer.

## Questions ouvertes

- [ ] **Réseaux annoncés** : l'application pare-feu fournit-elle au contrôleur la liste des réseaux locaux à annoncer, ou sont-ils déclarés dans le contrôleur ?
- [ ] **Interface avec l'application pare-feu** : sens et format des échanges par API.
- [ ] **Connexions des cinq sites** : déclarer pour chacune son rôle, la connexion directe possible en IPv4 et en IPv6, et l'éventuelle plage de ports.
