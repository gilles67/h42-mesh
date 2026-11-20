# h42-mesh — architecture du VPN maillé multi-sites

Nov 17, 2026 · @Gilles

Cinq maisons reliées en VPN maillé WireGuard, routées en BGP avec FRR (un AS par site), pilotées par un contrôleur et des agents en Python sur Debian, avec deux VPS qui hébergent le contrôleur et, grâce à leurs adresses publiques, servent naturellement de relais. Les connexions actives sont toujours préférées aux connexions de secours. Les zones, l'adressage des réseaux locaux et le pare-feu relèvent d'une application complémentaire.

## Les composants

L'application relie plusieurs maisons en VPN maillé : un contrôleur distribue la configuration, et les routeurs de chaque site montent des tunnels directs entre eux. Chaque site compte un ou deux routeurs, chacun avec une ou plusieurs connexions internet.

&#91;embedded content: architecture · contrôleur, 3 maisons, tunnels maillés\]

Exemple à trois maisons : chaque routeur reçoit sa configuration du contrôleur, puis le trafic circule directement entre les sites.

1. **Le contrôleur** : API seule, en Python (FastAPI, Pydantic, Tortoise ORM ; SQLite, PostgreSQL possible), sans interface intégrée, en principal sur le VPS 1 et en secours sur le VPS 2, base répliquée de l'un vers l'autre. Il garde l'inventaire des maillages, sites, routeurs et connexions, décide des tunnels et attribue leurs adresses, distribue la configuration, et collecte l'état des tunnels et des routes BGP remonté par les agents. Il échange avec l'application pare-feu par API, et publie automatiquement sa description OpenAPI.
2. **L'agent** : service systemd en Python sur chaque routeur Debian (x86 ou arm64). Il récupère sa configuration auprès du contrôleur (dont il connaît les deux adresses), applique les différences de façon idempotente avec pyroute2, génère les configurations de FRR et keepalived (Jinja2), et remonte l'état des liens.
3. **Le plan de données** : WireGuard en espace utilisateur avec **wireguard-go** (implémentation officielle en Go, licence MIT), et non le module du noyau. Chaque tunnel est un processus wireguard-go lancé dans la VRF de sa connexion internet : son socket UDP y est rattaché, tandis que son interface de tunnel reste dans la VRF par défaut, avec le routage BGP. Le module du noyau ne permet pas de rattacher simplement son socket à une VRF. Les clés privées sont générées sur le routeur et ne le quittent jamais ; seule la clé publique remonte au contrôleur.
4. **Les deux VPS** : routeurs ordinaires du site « Hub Home42 ». Leurs adresses publiques acceptent les connexions entrantes : chaque routeur garde un tunnel vers eux, et ils servent ainsi naturellement de relais, de chemin de secours et de passage pour les liens en CGNAT. Relayer n'est pas un rôle : tout routeur peut le faire, selon les connexions dont il dispose.
5. **L'interface graphique** : composant séparé, simple client de l'API du contrôleur. Application web monopage en TypeScript (React, Vite, Mantine, TanStack Query, React Flow pour la topologie), compilée en fichiers statiques : aucun serveur Node.js en production. Son client API est généré depuis la description OpenAPI du contrôleur, ce qui garde les modèles Pydantic comme seule source de vérité.

Principe clé : si le contrôleur tombe, les tunnels déjà établis continuent de fonctionner. Il configure, il ne fait pas passer le trafic.

## Difficultés techniques et réponses retenues

Chaque difficulté identifiée a désormais une réponse arrêtée ; le détail du routage et de l'adressage suit dans les sections dédiées.

| Difficulté | Enjeu | Réponse retenue |
| --- | --- | --- |
| Multi-WAN | Chaque tunnel doit sortir par la bonne connexion, sans exploser le nombre de tunnels | Tunnel direct dès qu'un côté accepte les connexions entrantes, relais par un autre site sinon ; une VRF par connexion internet |
| Détection de panne et bascule | Savoir quel lien est vivant et choisir le meilleur chemin | BGP avec FRR ; BFD rapide sur les tunnels actifs, temporisations lentes sur les tunnels de secours |
| Deux routeurs par site | Une seule passerelle visible pour les appareils de la maison | VRRP avec keepalived, qui suit l'état de la connexion active ; iBGP entre les deux routeurs |
| NAT et CGNAT | 4G, 5G et Starlink sont souvent en CGNAT pour l'IPv4 | Paramètre « connexion directe possible » par famille d'adresses, IPv6 privilégiée, relais par un autre site sinon |
| Plan d'adressage | Les réseaux des box se chevauchent souvent (192.168.1.0/24) | Adressage des réseaux locaux défini dans l'application pare-feu ; ce projet n'attribue que les adresses des routeurs et des tunnels |

## Maillages

Un maillage (*mesh*) est un ensemble indépendant de sites, routeurs, connexions et tunnels. Un même contrôleur pilote un ou plusieurs maillages distincts : aucun tunnel ni aucune route ne relie deux maillages.

- **Hiérarchie** : maillage → sites → routeurs → connexions internet. Un tunnel relie deux connexions d'un même maillage.
- **Numéro** : le contrôleur ne numérote pas les maillages. Le numéro (0 à 9) est géré directement par l'agent : il est défini dans sa configuration locale pour chaque maillage dont la machine fait partie, et doit seulement être unique sur cette machine. Une même machine numérote ainsi ses maillages 0, 1, 2…, et deux machines peuvent donner des numéros différents au même maillage. Ce numéro figure dans le nom des interfaces de tunnel (`wd0…`) et dans le calcul de la plage de ports du routeur. Dans la première version, un agent ne rejoint qu'un maillage : son numéro vaut 0 par défaut.
- **Portée des règles d'unicité** : nom et quadrigramme de site, numéros d'AS et paires d'adresses de tunnel (169.254) sont uniques **dans un maillage**. Deux maillages peuvent donc réutiliser les mêmes valeurs.
- **VPS** : un VPS est un routeur comme les autres, et non un type de site. Comme tout routeur, il est déclaré dans un site créé par l'utilisateur. Dans notre maillage, les deux VPS sont les routeurs `r0` et `r1` du site « Hub Home42 », de quadrigramme `root` : l'interface d'un routeur de maison vers le premier s'appelle par exemple `wd0c0rootr0c0`.
- **Rôles d'un VPS** : routeur, contrôleur, ou les deux. Un maillage peut n'avoir aucun VPS routeur et dépendre seulement d'un VPS contrôleur, qui ne fait alors pas partie du maillage.
- **Relais** : il n'y a pas de rôle de relais. Tout routeur peut relayer le trafic entre deux autres sites ; cela dépend seulement des tunnels que ses connexions permettent d'établir, et BGP choisit le chemin. En pratique, un site dont les connexions acceptent les connexions entrantes (comme le hub, avec ses adresses publiques) relie les connexions qui ne les acceptent pas. Si aucun site ne le permet, deux connexions qui n'acceptent ni l'une ni l'autre les connexions entrantes ne peuvent pas être reliées. Aucune préférence n'est imposée entre les relais possibles : BGP choisit librement, sans allongement du chemin AS ni exclusion de connexion. Un chemin par le hub et un chemin par une autre maison traversant autant d'AS, une maison peut porter sur son débit montant le trafic entre deux autres sites.
- **Routeur dans plusieurs maillages** (*prévu, pas dans la première version* : pour l'instant, un agent ne rejoint qu'un seul maillage, sur un seul contrôleur ; voir [todo.md](todo.md)) : une même machine (un VPS notamment) peut appartenir à plusieurs maillages. Elle est alors déclarée et enrôlée comme routeur dans chacun d'eux. Le premier maillage utilise la table de routage principale ; chaque maillage supplémentaire est placé dans une VRF, définie en option dans la configuration de l'agent. Les interfaces de tunnel et l'instance BGP de ce maillage sont rattachées à sa VRF, ce qui isole les maillages entre eux et permet de réutiliser les mêmes adresses d'un maillage à l'autre. Le trafic WireGuard chiffré reste dans la VRF de sa connexion internet.
- **Droits** : un utilisateur de l'interface ne voit et ne gère que les maillages qui lui sont attribués ; l'administrateur accède à tous (voir « Utilisateurs et droits »).

## Tunnels

Un tunnel relie entre elles deux connexions internet appartenant à deux routeurs de sites différents (maisons ou VPS). Les deux routeurs d'un même site ne sont jamais reliés par un tunnel de l'application. Ses deux extrémités sont donc des connexions, pas des routeurs : deux routeurs ayant chacun plusieurs connexions peuvent être reliés par plusieurs tunnels, un par paire de connexions retenue. Le contrôleur décide quels tunnels existent ; l'agent les crée et les supprime.

Paires de connexions retenues :

| Paire | Tunnel |
| --- | --- |
| Active ↔ active | Oui |
| Secours ↔ active | Oui |
| Secours ↔ secours | Jamais |

Dans tous les cas, il faut en plus qu'au moins un des deux côtés accepte les connexions entrantes (voir « Établissement d'un tunnel direct ») : c'est le paramètre « connexion directe possible » qui décide, sans réglage supplémentaire. Une connexion de secours, souvent en CGNAT, se relie ainsi aux connexions actives qui acceptent les entrées, en particulier celles du hub.

- **Un tunnel = une interface WireGuard avec un seul pair.** Chaque pair autorise `0.0.0.0/0` et `::/0` : WireGuard ne fait aucun choix de route, c'est FRR (BGP) qui choisit le tunnel de sortie, sans que le contrôleur ait à prévoir la table de routage. WireGuard interdisant que deux pairs d'une même interface aient les mêmes `AllowedIPs`, chaque tunnel a sa propre interface.
- **Aucune route installée par WireGuard** : seules les routes apprises par BGP utilisent les tunnels.
- **Extrémités `a` et `b`** : par convention, la connexion `a` écoute et la connexion `b` établit la communication. `a` est donc une connexion qui accepte les connexions entrantes ; quand les deux connexions les acceptent, `a` est celle du site dont l'AS est le plus faible (les deux connexions sont toujours dans des sites différents, d'AS différents) ; un tunnel n'utilise que les familles d'adresses dans lesquelles `a` les accepte (le repli de l'IPv6 vers l'IPv4 suppose que `a` accepte aussi l'IPv4 en entrée).
- **Clés** : chaque extrémité a sa propre paire de clés WireGuard pour ce tunnel, générée par son agent ; la clé privée ne quitte pas le routeur et le contrôleur enregistre les deux clés publiques. Le tunnel a en plus une clé pré-partagée WireGuard (PSK), qui ajoute une couche de chiffrement symétrique ; elle est générée par le contrôleur à la création du tunnel, au format de `wg genpsk` (32 octets aléatoires encodés en base64). Contrairement aux clés privées, la PSK est connue des deux extrémités et transite par le contrôleur : elle est stockée chiffrée et n'est transmise qu'aux agents des deux routeurs concernés, jamais à l'interface ni à l'application pare-feu.
- **Nom de l'interface** : `wd` + numéro du mesh + `c` et numéro de la connexion locale + quadrigramme du site distant + `r` et numéro du routeur distant + `c` et numéro de la connexion distante. Exemple : `wd0c0parir0c0` désigne, dans le mesh 0, le tunnel qui part de la connexion locale 0 vers la connexion 0 du routeur 0 du site `pari`. Le nom fait 13 caractères (Linux en autorise 15) et est unique sur un routeur, puisqu'un tunnel relie une seule paire de connexions. Il se lit directement dans `ip link`, `wg show` et la configuration de FRR.
- **Adresses IPv4 dans le tunnel** : une paire d'adresses (/31) prise dans `169.254.0.0/16` (adresses locales au lien), unique pour tout le maillage et tirée au hasard par le contrôleur parmi les paires libres. L'unicité est garantie par une contrainte en base, avec un nouveau tirage en cas de conflit. Les sessions BGP passant en IPv6 locale au lien, ces adresses servent au diagnostic en IPv4 (`ping` d'un bout à l'autre du tunnel) ; la première adresse de la paire va à l'extrémité `a`, la seconde à `b` ; elles ne sont jamais annoncées. Sont exclus du tirage `169.254.0.0/24` et `169.254.255.0/24` (réservés par la RFC 3927), ainsi que `169.254.169.0/24`, qui contient l'adresse du service de métadonnées des hébergeurs (`169.254.169.254`).
- **Adresses IPv6 dans le tunnel** : une paire d'adresses locales au lien (/127), propre à chaque tunnel et **déduite de sa paire IPv4** : les deux derniers octets de `169.254.0.0/16`, avec le préfixe `fe80::a9fe:` (169.254 en hexadécimal). Par exemple, la paire `169.254.12.34/31` donne `fe80::a9fe:c22/127` : `a` prend `fe80::a9fe:c22` et `b` `fe80::a9fe:c23`. L'unicité de la paire IPv4 dans le maillage garantit celle de la paire IPv6, sans tirage supplémentaire ; chaque adresse vue dans un journal ou dans FRR désigne ainsi un seul tunnel. Le contrôleur enregistre la paire avec le tunnel (`ipv6_network`) ; l'agent la pose sur l'interface (une interface WireGuard n'en reçoit pas automatiquement). Elles portent l'unique session BGP du tunnel et ne sont jamais annoncées.
- **Ports** : chaque extrémité a un port fixe pour le tunnel, choisi par son routeur. Le port de `a` est celui que `b` contacte ; celui de `b` reste le même d'une connexion à l'autre, ce qui rend le trafic prévisible (règles de la box, diagnostic). WireGuard écoute sur toutes les adresses de la machine : un port n'est donc utilisable qu'une fois par routeur, toutes connexions confondues.
  - **Plage par routeur** : chaque routeur reçoit une plage de 1000 ports, calculée à partir de son maillage et de son numéro dans le site : `42000 + 2000 × numéro du maillage + 1000 × numéro du routeur`. 42000 est une constante, fixée dans tous les agents. Maillage 0 : `r0` 42000 à 42999, `r1` 43000 à 43999 ; maillage 1 : 44000 à 45999 ; maillage 9 : 60000 à 61999. Les deux routeurs d'une maison, souvent derrière la même IPv4 publique de la box, n'utilisent ainsi jamais les mêmes ports, et une machine présente dans plusieurs maillages a une plage distincte pour chacun.
  - **Attribution par l'agent** : pour chaque tunnel à créer, l'agent de chaque extrémité choisit un port libre dans sa plage (dans l'intersection avec la plage de ports de la connexion si la configuration locale de l'agent en déclare une) et le remonte au contrôleur, qui stocke les ports des deux connexions et transmet celui de `a` à `b`. L'agent est le mieux placé pour savoir quels ports sont réellement libres sur sa machine. Le contrôleur renvoie à chaque agent le port déjà enregistré, que l'agent réutilise : un tunnel garde ses ports d'une configuration à l'autre.
  - **Réservation** : ces ports sont dans la plage des ports éphémères de Linux (32768 à 60999), que le noyau attribue aux connexions sortantes. L'agent réserve la plage de son routeur (`net.ipv4.ip_local_reserved_ports`), pour qu'aucune connexion sortante ne la prenne avant WireGuard.
- **Une seule famille d'adresses** (IPv6 ou IPv4) pour joindre l'autre extrémité, choisie selon les règles d'établissement d'un tunnel direct.
- **Rôle** : celui de la plus faible des deux connexions (une connexion de secours rend le tunnel de secours). Il détermine la communauté BGP « secours » et la détection de panne (BFD ou non).
- **Chemin relayé** : ce n'est pas un tunnel, mais deux tunnels (connexion du site A ↔ connexion d'un site intermédiaire, puis connexion de ce site ↔ connexion du site B) enchaînés par BGP, par exemple via le hub. Les deux VPS du hub sont reliés par leur lien interne, hors de l'application, comme les deux routeurs d'une maison.
- **Enregistrement** : les tunnels sont enregistrés par le contrôleur, pour que les adresses, les ports (choisis par l'agent, voir ci-dessus) et les noms d'interface restent stables d'une configuration à l'autre.

Conséquences :

- WireGuard ne filtre plus les adresses source reçues d'un pair ; ce contrôle relève de l'application pare-feu. `rp_filter` est en mode souple (loose) sur les interfaces de tunnel.
- **VRF des connexions internet** : les interfaces des connexions internet sont, sans exception, chacune dans une VRF dédiée, distincte de la VRF par défaut. Le processus wireguard-go d'un tunnel est lancé dans la VRF de sa connexion (`ip vrf exec`) : le trafic chiffré sort donc forcément par cette connexion, avec sa propre route par défaut, et jamais par un tunnel. La VRF par défaut ne contient que le réseau local, les interfaces de tunnel et le routage BGP. Les VRF des connexions et le rattachement des interfaces sont créés par la configuration du système (par exemple `/etc/network/interfaces` ou systemd-networkd), pas par l'agent : l'administrateur les nomme librement et déclare le nom de chacune dans la configuration locale de l'agent. L'agent vérifie qu'elle existe et signale une erreur sinon. L'accès à Internet depuis la VRF par défaut (mises à jour, DNS et NTP du routeur, accès Internet du réseau local) n'est pas traité par ce projet : il est confié à une application tierce (voir [todo.md](todo.md)). Prérequis : l'heure du routeur doit être synchronisée, car les JWT de l'agent ne sont valables qu'une minute environ.

**Échanges de l'agent avec le contrôleur** : l'agent ne dépend pas de l'accès à Internet de la VRF par défaut. Il émet ses requêtes depuis la VRF d'une connexion internet (socket rattaché à la VRF), en essayant d'abord les connexions actives, par ordre de priorité, puis les connexions de secours, et il résout lui-même le nom des contrôleurs avec un **client DNS intégré**, qui interroge les serveurs DNS directement depuis la VRF de la connexion, sans passer par la résolution du système (liée à la VRF par défaut). Serveurs DNS interrogés par défaut : `1.1.1.1`, `2606:4700:4700::1111` (Cloudflare), `8.8.8.8` et `2001:4860:4860::8888` (Google) ; la liste est modifiable dans la configuration locale de l'agent. Sur une connexion, l'agent n'interroge que les serveurs de la famille d'adresses disponible. La connexion TLS est ensuite établie vers l'adresse obtenue, en vérifiant le certificat pour le nom du contrôleur. Aucun site n'annonce de route par défaut ni d'adresse publique en BGP.

## Routage BGP

Chaque site a son propre AS privé, y compris le site des VPS (« Hub Home42 ») ; un chemin direct traverse donc moins d'AS qu'un chemin relayé et est naturellement préféré.

Le numéro d'AS est défini par l'utilisateur pour chaque site, comme n'importe quel attribut du site. Le contrôleur vérifie seulement qu'il est unique au sein du maillage et qu'il appartient à la plage privée sur 4 octets, de 4200000000 à 4294967294 (RFC 6996). Il est écrit en notation décimale simple (asplain) dans FRR. Exemple de répartition :

| Site | AS (4 octets, privé) |
| --- | --- |
| Hub Home42 (root) | 4200000000 |
| Maisons 1 à 5 | 4200000001 à 4200000005 |

- **Entre sites** (y compris vers le hub) : une seule session eBGP par tunnel WireGuard, établie sur la paire d'adresses IPv6 locales au lien du tunnel (par exemple `fe80::a9fe:c22` / `fe80::a9fe:c23`), qui porte les routes IPv4 et IPv6 ; les routes IPv4 ont un prochain saut IPv6 (RFC 8950, option `extended-nexthop` de FRR). C'est le même mécanisme que pour la session iBGP. Deux tunnels entre deux routeurs portent deux sessions.
- **Entre les deux routeurs d'un site** : session iBGP (même AS), qui passe par le lien interne du site, jamais par un tunnel de l'application :
  - dans une maison, le réseau local ;
  - dans un site de deux VPS (comme « Hub Home42 »), sans réseau local commun, un tunnel mis en place par l'administrateur des VPS, hors du cadre de l'application, et vu par elle comme un réseau local.
  
  La session s'établit sur les adresses IPv6 locales au lien (fe80::) de l'interface du lien interne ; l'IPv6 est supposée activée sur ce lien.
  - Le lien interne est entièrement décrit dans la configuration locale de l'agent de chacun des deux routeurs : le nom de l'interface et l'adresse fe80:: de l'autre routeur sur ce lien. Le contrôleur n'en sait rien et n'intervient pas dans la session iBGP.
  - La session est déclarée explicitement dans FRR (`neighbor fe80::… interface <interface>`). On évite la découverte automatique de FRR (*BGP unnumbered*), qui émet des annonces de routeur (RA) : sur le réseau local d'une maison, les appareils pourraient s'en servir comme passerelle, et FRR pourrait tenter d'établir une session avec la box, qui émet elle aussi des RA.
  - L'adresse fe80:: d'une interface doit rester stable : c'est le cas par défaut sous Debian (adresse dérivée de l'adresse MAC). Si la carte réseau change, il faut mettre à jour la configuration de l'autre routeur.
  - On ne pose pas non plus d'adresse fe80:: fixe : sur un réseau local, elle pourrait entrer en conflit avec celle de la box (souvent fe80::1).
  - Une seule session porte les routes IPv4 et IPv6 : les routes IPv4 ont alors un prochain saut IPv6 (RFC 8950, option `extended-nexthop` de FRR), ce que le noyau Linux de Debian 13 accepte.
  - Sur un site de VPS, l'interface du tunnel monté par l'administrateur doit porter une adresse fe80:: : une interface WireGuard n'en reçoit pas automatiquement.

  Les routes apprises en eBGP ont pour prochain saut une adresse de tunnel (169.254 ou fe80::) que l'autre routeur du site ne sait pas joindre : la session iBGP utilise donc `next-hop-self`. Le VRRP (keepalived) ne concerne que les sites qui ont un réseau local à desservir, pas un site de VPS.
- **Identifiant BGP du routeur** (*router-id*) : ni attribué ni stocké par le contrôleur ; FRR le choisit lui-même (voir le point d'attention ci-dessous).
- **Annonces** : dans la première version, FRR annonce les réseaux connectés de la VRF par défaut (`redistribute connected`). L'échange avec l'application pare-feu, qui pourra préciser plus tard les réseaux à annoncer, est reporté (voir [todo.md](todo.md)). La liste des réseaux annoncés n'est pas déclarée dans le contrôleur.
  - **Filtre indispensable** : les interfaces des connexions internet étant dans leurs propres VRF, leurs réseaux ne sont pas « connectés » dans la VRF par défaut. L'agent génère tout de même un filtre (*route-map*) qui écarte les interfaces de tunnel (`wd…`, 169.254.0.0/16, fe80::/10), la boucle locale et les interfaces de conteneurs.
  - **Point d'attention** : deux sites qui utilisent le même réseau local (par exemple 192.168.1.0/24) l'annoncent tous les deux, et BGP n'en retient qu'un ; l'autre site devient injoignable pour ce réseau. L'adressage des réseaux locaux relève de l'application pare-feu.
- **Supervision des routes** : chaque agent relève la table BGP de FRR (toutes les routes reçues, pas seulement les meilleures, et celles qu'il annonce) et la remonte au contrôleur, à intervalle régulier ou dès qu'elle change. Le contrôleur remplace à chaque fois l'état précédent : il n'y a pas d'historique. Les routes annoncées par chaque routeur montrent les réseaux réellement exportés.
- **Cas limite** : si les deux routeurs d'un site perdent le lien entre eux, la protection anti-boucle de BGP les empêche de se joindre via le VPN. Une option FRR existe pour le contourner, à n'utiliser qu'avec prudence.

> **Point d'attention : trafic émis par le routeur lui-même.** Les adresses des tunnels (169.254 et fe80::) ne sont jamais annoncées, et aucune adresse propre au routeur n'est annoncée en BGP. Un paquet émis par le routeur lui-même vers un autre site (un `ping` de diagnostic, par exemple) prend par défaut comme source l'adresse du tunnel de sortie, et la réponse ne peut pas revenir. Ce n'est pas un défaut : seul le diagnostic depuis le routeur est concerné, et les échanges entre l'agent et le contrôleur passent par Internet, pas par le maillage. Pour tester l'accès à un autre réseau depuis un routeur, utiliser comme source son adresse sur le réseau local, par exemple `ping -I 192.168.10.1 192.168.20.10` ou `ping -I eth1 …`. Sur un routeur sans réseau local annoncé (un VPS du hub), seul le test d'un bout à l'autre d'un tunnel est possible (`ping 169.254.x.y`).

> **Point d'attention : collisions d'identifiant BGP.** Chaque routeur BGP se présente à ses voisins avec un identifiant sur 32 bits, écrit comme une adresse IPv4, qui doit être différent de celui de chacun de ses voisins. Le contrôleur n'en attribue pas : FRR le choisit lui-même, en prenant la plus grande adresse IPv4 de la machine (adresse de réseau local ou de tunnel 169.254 comprises). Deux risques en découlent :
> - **collision** : deux routeurs voisins peuvent obtenir le même identifiant, notamment quand deux maisons utilisent le même plan d'adressage local (par exemple 192.168.1.x). FRR peut alors refuser la session : elle ne s'établit pas, et le journal de FRR signale un conflit d'identifiant ;
> - **instabilité** : l'identifiant peut changer quand une interface ou un tunnel apparaît ou disparaît, ce qui redémarre les sessions BGP du routeur.
>
> En cas de collision, vérifier les identifiants avec `vtysh -c "show bgp summary"` sur les deux routeurs et modifier l'une des adresses en cause. Une option de l'agent permettant de fixer l'identifiant pourra être ajoutée si le cas se présente.

## Modèle de connexion et précédence

Une connexion de secours a toujours une priorité moindre qu'une connexion active. Le comportement de chaque connexion est déclaré dans le contrôleur, pas déduit de son type.

| Attribut | Valeurs | Rôle |
| --- | --- | --- |
| Rôle | active / secours | Précédence de routage, toujours respectée |
| Priorité | nombre, optionnel | Départage les connexions d'un même rôle |
| Connexion directe possible | aucune / IPv4 / IPv6 / les deux | Familles dans lesquelles la connexion accepte les connexions entrantes (peut-elle recevoir des tunnels ?) |
| Opérateur | déduit de l'adresse publique | Informatif ; voir ci-dessous |
| Description | texte libre, optionnel | Informatif (par exemple « fibre Orange, box au garage ») |

La plage de ports d'une connexion (par exemple une IPv4 partagée, ou un pare-feu de box qui n'ouvre que certains ports) n'est pas déclarée dans le contrôleur : elle fait partie de la configuration locale de l'agent. Elle vaut pour l'IPv4 comme pour l'IPv6, car un tunnel écoute sur le même port dans les deux familles. Le cas des connexions facturées au volume sera défini plus tard (voir [todo.md](todo.md)).

**Opérateur** : le contrôleur déduit l'opérateur de chaque connexion de son adresse publique (IPv4 si elle est connue, sinon IPv6), avec la base gratuite GeoLite2 ASN de MaxMind, et le met à jour à chaque changement d'adresse.

- **Accès à la base** : il faut un compte MaxMind gratuit et une clé de licence ; la base est téléchargée et mise à jour (deux fois par semaine) avec l'outil `geoipupdate`. Elle n'est ni dans le dépôt ni dans l'image : le contrôleur la lit dans un fichier dont le chemin est donné par une variable d'environnement (par exemple `H42_MESH_GEOLITE2_ASN_FILE`). Sans ce fichier, l'opérateur reste vide.
- **Licence** : la licence de GeoLite2 (EULA) impose de citer MaxMind dans la documentation et dans l'interface, par exemple « This product includes GeoLite2 data created by MaxMind, available from https://www.maxmind.com ». La base n'étant pas distribuée avec le projet, la licence MIT du code n'est pas affectée.
- **Lecture** : bibliothèque `maxminddb` (licence Apache 2.0).

Chaque connexion a au plus deux adresses publiques : une IPv4 et une IPv6. Elles ne sont pas saisies dans le contrôleur : elles sont découvertes par le contrôleur, ce qui fonctionne aussi dans un maillage sans VPS routeur, ou bien forcées par l'agent.

- **Principe** : pour chaque connexion et chaque famille d'adresses, l'agent envoie une requête authentifiée de reconnaissance des adresses publiques au contrôleur, en sortant par cette connexion (requête émise depuis la VRF de la connexion). La requête contient l'identifiant (UID) de la connexion. Le contrôleur enregistre l'adresse source qu'il voit. En IPv4 derrière une box, c'est l'adresse publique après NAT.
- **Adresse forcée par l'agent** : dans la configuration locale d'une connexion, l'agent peut forcer l'adresse IPv4, l'adresse IPv6, ou les deux. Il envoie alors dans la requête de reconnaissance l'UID de la connexion et l'adresse souhaitée, que le contrôleur enregistre à la place de l'adresse source vue. C'est indispensable pour une machine qui est à la fois routeur et contrôleur : ses requêtes vers son propre contrôleur ne sortent pas sur Internet et n'arrivent pas avec son adresse publique. Le contrôleur vérifie que la connexion appartient bien au routeur authentifié et que l'adresse est de la bonne famille.
- **Contrôleur joignable dans les deux familles** : les noms des VPS contrôleurs ont un enregistrement A et un enregistrement AAAA.
- **Derrière Traefik** : le contrôleur lit l'adresse d'origine dans l'en-tête transmis par Traefik, et ne fait confiance à cet en-tête que s'il vient de Traefik ; sinon un client pourrait annoncer n'importe quelle adresse.
- **IPv6** : l'agent impose comme source l'adresse stable de la connexion, jamais une adresse temporaire (extensions de confidentialité), qui changerait régulièrement.
- **Mise à jour** : la découverte est refaite périodiquement et à chaque changement d'adresse détecté par l'agent ; un changement d'adresse fait recalculer la configuration des tunnels concernés.
- **Limite** : la découverte donne l'adresse, pas la joignabilité. Qu'une connexion accepte les connexions entrantes reste déclaré par l'utilisateur (« connexion directe possible »).

### Établissement d'un tunnel direct

Un tunnel direct est possible dès qu'un seul des deux côtés accepte les connexions entrantes ; l'autre côté l'initie et le maintient par un *keepalive* WireGuard toutes les 25 secondes.

1. **IPv6 d'abord**, si les deux côtés l'ont et qu'au moins un l'accepte en entrée.
2. **Sinon IPv4**, si au moins un côté l'accepte en entrée.
3. **Sinon, relais par un autre site** (en pratique le hub, joignable en IPv4 et en IPv6).

Un tunnel WireGuard n'a qu'une adresse de destination à la fois : un tunnel n'utilise qu'une famille à la fois.

**Repli de l'IPv6 vers l'IPv4** : déclarer l'IPv6 possible ne garantit pas qu'elle fonctionne (pare-feu de la box, panne du fournisseur). Quand les deux familles sont possibles, le contrôleur transmet au côté qui initie les deux adresses de destination, IPv6 en premier. Si aucune poignée de main WireGuard (*handshake*) n'aboutit en IPv6 dans le délai de repli, l'agent bascule de lui-même sur l'IPv4, sans attendre le contrôleur, et lui signale la famille utilisée. Il retente l'IPv6 périodiquement et y revient dès qu'elle fonctionne. Le côté qui accepte les connexions n'a rien à changer : il écoute dans les deux familles et répond à l'adresse d'où vient la poignée de main. Si aucune famille ne fonctionne, le tunnel est simplement hors service : les routes passent par un autre site. Les deux délais ont des valeurs par défaut et sont modifiables pour chaque connexion dans la configuration de l'agent : **délai de repli 30 secondes** sans poignée de main réussie, **10 minutes** entre deux nouvelles tentatives en IPv6.

### Ordre de préférence des chemins

Un tunnel prend le rôle le plus faible de ses deux extrémités.

1. Direct, active ↔ active
2. Relayé par un autre site (en pratique le hub), sur connexions actives
3. Direct, impliquant une connexion de secours
4. Relayé par un autre site, impliquant une connexion de secours

Toute route reçue par un tunnel de secours porte une communauté BGP large « secours », qui la suit dans tout le réseau ; chaque routeur donne une préférence locale basse aux routes qui la portent. Sans cela, un chemin relayé paraîtrait actif alors que le site intermédiaire atteint la destination par une connexion de secours.

- **Valeur** : calculée à partir de l'AS du site qui la pose, `<AS du site>:1:2` (par exemple `4200000003:1:2`), selon l'usage des communautés larges (RFC 8092), dont la première partie est l'AS de celui qui la définit. Rien n'est à configurer, et la communauté indique quel site a reçu la route par un tunnel de secours.
- **Pose** : à la réception, sur chaque session BGP d'un tunnel de secours, par le routeur qui reçoit la route.
- **Reconnaissance** : chaque routeur reconnaît la communauté quel que soit l'AS qui la porte, par une expression régulière (`^[0-9]+:1:2$`) dans une liste de communautés larges de FRR, plutôt que par la liste des AS du maillage, qui changerait à chaque ajout de site.
- **Transmission** : les communautés larges sont transmises sur toutes les sessions (eBGP et iBGP).

### Détection de panne

| Tunnel | Détection |
| --- | --- |
| Actif | BFD rapide, bascule en moins d'une seconde |
| Secours | Temporisations BGP lentes, sans BFD |

Sur un site à deux routeurs, celui qui porte la connexion active est la passerelle VRRP principale.

## Configuration locale de l'agent

Une partie de la configuration ne vient pas du contrôleur : elle décrit la machine elle-même et reste dans le fichier de configuration de l'agent.

| Niveau | Élément | Remarque |
| --- | --- | --- |
| Appartenance à un maillage | Adresses des deux contrôleurs, clés de l'agent | Une seule appartenance dans la première version (un maillage, un contrôleur) ; plusieurs plus tard |
| Appartenance à un maillage | Numéro du maillage (0 à 9) | Unique sur la machine ; sert au nom des interfaces et à la plage de ports |
| Appartenance à un maillage | VRF | Plus tard, avec plusieurs maillages : le premier maillage utilise la table principale, chaque maillage supplémentaire une VRF |
| Routeur d'un site à deux routeurs | Lien interne : nom de l'interface et adresse fe80:: de l'autre routeur | Sert à la session iBGP, sans le contrôleur |
| Agent | Serveurs DNS du client intégré | Par défaut `1.1.1.1`, `2606:4700:4700::1111` (Cloudflare), `8.8.8.8` et `2001:4860:4860::8888` (Google) |
| Connexion (désignée par son UID) | Interface physique et VRF de la connexion | Obligatoires : le processus wireguard-go des tunnels de la connexion et la découverte des adresses s'exécutent dans cette VRF |
| Connexion | Plage de ports | Facultative : ports utilisables sur la connexion, en IPv4 comme en IPv6 (IPv4 partagée, ports ouverts par la box) |
| Connexion | Adresse IPv4 et/ou IPv6 forcée | Facultative ; remplace l'adresse vue par le contrôleur |
| Connexion | Délais du repli IPv6 → IPv4 | 30 secondes et 10 minutes par défaut |

La passerelle de chaque connexion n'est pas déclarée : l'agent la relève sur l'interface physique (route par défaut obtenue par DHCP ou par les annonces de routeur IPv6). Le contrôleur ne connaît ni les numéros de maillage, ni les noms d'interface, ni les VRF, ni le lien interne des sites à deux routeurs.

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
- **Renouvellement** : une nouvelle clé publique signée avec l'ancienne, sans nouvel enrôlement. Le contrôleur remplace simplement l'ancienne clé, sans en garder l'historique.

### Utilisateurs et droits

- **Administrateur** : un compte administrateur unique crée les autres utilisateurs ; c'est le seul compte qui accède globalement à tous les maillages du contrôleur.
- **Création à l'installation** : l'administrateur est généré lors de l'installation du contrôleur. Proposition de mise en œuvre : au premier démarrage, si la base ne contient aucun utilisateur, le contrôleur crée le compte administrateur avec un mot de passe aléatoire, affiché une seule fois dans son journal ; à la première connexion, l'administrateur doit changer ce mot de passe et enregistrer sa double authentification TOTP.
- **Secours** : une commande du contrôleur, lancée sur le VPS (`podman exec`), réinitialise le mot de passe et la double authentification de l'administrateur, pour ne jamais perdre l'accès.
- **Autres utilisateurs** : ils ne voient que les maillages qui leur sont attribués, avec un niveau d'accès par maillage :
  - **gestion** : modifier le maillage (sites, routeurs, connexions, jetons d'enrôlement) ;
  - **lecture seule** : visualiser l'ensemble des informations du maillage (inventaire, configuration, état des tunnels), sans rien modifier. Un utilisateur en lecture seule peut suivre plusieurs maillages.
- **Attribution des accès** : un utilisateur qui gère un maillage peut accorder ou retirer, pour ce maillage, l'accès en gestion ou en lecture seule à d'autres utilisateurs existants. L'administrateur le peut pour tous les maillages. Comme l'administrateur garde toujours l'accès à tout, aucun maillage ne peut devenir inaccessible.
- **Création de maillages** : un utilisateur peut recevoir de l'administrateur le droit de créer de nouveaux maillages ; il obtient alors l'accès en gestion aux maillages qu'il crée.

| Compte | Utilisateurs | Maillages visibles | Créer un maillage |
| --- | --- | --- | --- |
| Administrateur | Crée et gère | Tous, en gestion | Oui |
| Utilisateur | Non ; accorde ou retire les accès aux maillages qu'il gère | Ceux qui lui sont attribués, en gestion ou en lecture seule | Si l'administrateur lui en donne le droit |

### Secrets stockés par le contrôleur

Les secrets que le contrôleur doit conserver (PSK des tunnels, secrets TOTP des utilisateurs) sont chiffrés en base.

- **Phrase secrète** : le chiffrement repose sur une phrase secrète stockée dans un fichier, dont le chemin est donné par une variable d'environnement (par exemple `H42_MESH_PASSPHRASE_FILE`). Sur le VPS, ce fichier est fourni au conteneur comme secret Podman, jamais placé dans l'image ni dans le dépôt.
- **Stockage d'un secret** : chaque secret est enregistré avec ce qu'il faut pour le déchiffrer, dans un objet JSON, par exemple `{"v": 1, "kdf": "scrypt", "salt": "…", "nonce": "…", "ciphertext": "…"}` (valeurs binaires encodées en base64). Le **sel de dérivation est donc stocké à côté des données**, propre à chaque secret ; le numéro de version et le nom de la méthode de dérivation permettront d'en changer plus tard sans casser les secrets existants.
- **Mise en œuvre proposée** : une clé dérivée de la phrase secrète et du sel (dérivation volontairement lente, par exemple scrypt), et un chiffrement authentifié (AES-GCM ou ChaCha20-Poly1305), avec la bibliothèque `cryptography` (licences Apache 2.0 et BSD). La dérivation étant lente, le contrôleur garde en mémoire les clés déjà dérivées, pour ne pas la refaire à chaque lecture d'une PSK.
- **Phrase secrète erronée** : le chiffrement authentifié la détecte (le déchiffrement échoue). Au démarrage, après les migrations, le contrôleur essaie de déchiffrer un secret existant et s'arrête avec un message clair en cas d'échec.
- **Haute disponibilité** : les deux contrôleurs (étape 6) utilisent la même phrase secrète.
- **Perte de la phrase secrète** : les secrets deviennent illisibles ; il faut régénérer les PSK de tous les tunnels et faire réenregistrer la double authentification des utilisateurs. La phrase secrète doit donc être sauvegardée à part.

### Autres mesures

- **Clés distinctes** : la clé de signature Ed25519 est séparée de la clé WireGuard (X25519), et aucune clé privée ne quitte le routeur.
- **Utilisateurs de l'interface** : session par cookie sécurisé, double authentification TOTP et limitation des tentatives de connexion, l'interface et l'API d'administration étant joignables depuis Internet.
- **Relais** : le trafic relayé est déchiffré puis rechiffré sur le routeur intermédiaire (VPS ou maison), qui le voit en clair. D'où des routeurs durcis (mises à jour, SSH par clé uniquement), en particulier les VPS, et des protocoles chiffrés de bout en bout pour les flux sensibles, comme la vidéo.

## Déploiement sur les VPS

Sur chaque VPS, sous Debian 13, l'API, l'interface et le proxy tournent en conteneurs Podman ; le relais tourne sur l'hôte. Un VPS est ainsi un routeur comme les autres, géré par le même agent que les maisons.

| Élément | Exécution | Remarque |
| --- | --- | --- |
| Traefik | Conteneur | Point d'entrée HTTPS unique, certificats Let's Encrypt automatiques |
| Contrôleur (FastAPI) | Conteneur | Base SQLite dans un volume ; PostgreSQL en conteneur à partir de l'étape 6 |
| Interface (fichiers statiques) | Conteneur léger (nginx ou équivalent) | Traefik route mais ne sert pas de fichiers |
| wireguard-go, FRR | Hôte | Manipulent les interfaces réseau et les VRF |
| Agent Python | Hôte | Pilote WireGuard et FRR |

- **Lancement** : Quadlet, qui fait gérer chaque conteneur par systemd (disponible à partir de Podman 4.4, d'où Debian 13).
- **Routage Traefik** : configuration par fichier, versionnée dans le dépôt ; / vers l'interface, /api vers le contrôleur. Le socket Podman n'est pas exposé à Traefik.
- **Nommage** : un nom par VPS (vps1, vps2) pour une validation HTTP simple des certificats ; les agents connaissent les deux adresses.
- **Ports** : un conteneur rootless n'écoute pas sur 80 et 443 sans réglage système ; à prévoir pour Traefik.
- **Dépôt** : un seul dépôt avec les dossiers controller/, agent/ et gui/.

## Base de données du contrôleur

Le contrôleur accède à sa base par Tortoise ORM, asynchrone comme FastAPI : SQLite d'abord, PostgreSQL possible sans changer les modèles, en modifiant une seule variable de configuration (l'adresse de la base).

- **Modèle de données** : entités, champs, relations et contraintes décrits dans [data-model.md](data-model.md).
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
| État de l'agent | h42-mesh-agent status, ou h42-mesh-agent sans commande |
| Quadrigramme de site | 4 caractères en minuscules (a-z, 0-9), unique dans le mesh, défini en plus du nom du site ; les VPS en ont un aussi (par exemple vps1, vps2) |
| Numéro de routeur | r0, r1 : un chiffre, unique dans le site |
| Numéro de connexion | c0 à c9 : un chiffre, unique sur le routeur |
| Interface de tunnel | wd + mesh + connexion locale + quadrigramme distant + routeur distant + connexion distante, par exemple wd0c0parir0c0 |

Le projet est publié sous licence MIT. Avant la publication en open source, vérifier que le nom est libre sur GitHub et PyPI.

### Langue du code

Tout le code du projet est écrit en anglais :

- identifiants : variables, fonctions, classes, modules, types et interfaces TypeScript, composants React ;
- schéma de données : modèles Tortoise ORM, tables, colonnes, valeurs énumérées (par exemple `active` / `backup` pour le rôle d'une connexion) ;
- API : routes, paramètres, champs JSON, codes et messages d'erreur ;
- configuration : clés des fichiers de configuration, variables d'environnement (`H42_MESH_…`) ;
- commentaires, docstrings, messages de journal, noms et données de test ;
- messages de commit.

La documentation de conception (`docs/`, ce document compris) reste en français.

**Langue de l'interface** : l'interface est en anglais, avec la possibilité de la traduire dans un second temps. Pour que la traduction ne demande pas de réécrire les composants, les textes affichés passent dès le départ par un mécanisme de traduction (i18n, par exemple la bibliothèque react-i18next, sous licence MIT) : chaque texte est désigné par une clé, et l'anglais est la première et, pour l'instant, la seule langue fournie. Les valeurs de l'API (`active`, `backup`…) sont aussi affichées par ce mécanisme, ce qui permettra de les traduire.

Raisons : projet open source sous licence MIT, cohérence avec les écosystèmes Python et TypeScript, et code lisible par d'éventuels contributeurs non francophones.

## Spécifications des composants

Chaque composant a son fichier de spécification, qui détaille ce document : [contrôleur](specs/controller.md), [agent](specs/agent.md), [interface](specs/gui.md).

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

- [ ] **Services des VPS** : Traefik, le contrôleur et SSH doivent être joignables sur l'adresse publique, qui est dans la VRF de la connexion. Les lancer dans cette VRF, ou accepter depuis la VRF par défaut les connexions arrivant par une VRF (`net.ipv4.tcp_l3mdev_accept`) ?
- [ ] **Performances de wireguard-go** : un processus par tunnel ; à vérifier par un test sur Raspberry Pi 5 et sur un pare-feu x86 (voir [todo.md](todo.md)).
