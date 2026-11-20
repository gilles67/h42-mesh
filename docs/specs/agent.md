# Spécification — agent (`agent/`)

> **Statut : brouillon.** Ce fichier détaille, pour l'agent, les décisions de [architecture.md](../architecture.md), qui reste la référence. Ce qui n'y figure pas encore est marqué *proposition*.

## Rôle

Service systemd (`h42-mesh-agent.service`) en Python, sur chaque routeur Debian 13 (x86_64 ou arm64), maison ou VPS. Il :

- s'enrôle auprès du contrôleur et s'authentifie ensuite par JWT signé ;
- récupère la configuration voulue et l'applique de façon **idempotente** (il compare l'état voulu à l'état réel et n'applique que les différences) ;
- pilote wireguard-go, FRR et keepalived, sans réimplémenter ce qu'ils font ;
- remonte au contrôleur les adresses publiques, les clés et ports des tunnels, l'état des tunnels et la table BGP.

Si le contrôleur est injoignable, il garde la dernière configuration appliquée : les tunnels et le routage continuent de fonctionner.

## Première version

Un agent rejoint **un seul maillage, sur un seul contrôleur** (numéro de maillage 0). Le multi-maillage et le multi-contrôleur sont reportés (voir [todo.md](../todo.md)) ; le numéro de maillage reste présent dans les noms d'interface et le calcul des ports pour ne pas les rendre impossibles.

## Commandes

| Commande | Rôle |
| --- | --- |
| `h42-mesh-agent enroll --controller … --token …` | Génère la paire de clés Ed25519, s'enrôle, enregistre l'identifiant du routeur |
| `h42-mesh-agent run` | Boucle principale ; l'unité systemd lance explicitement `run` |
| `h42-mesh-agent status` | Affiche l'état local de l'agent (voir ci-dessous) ; **obligatoire** |
| `h42-mesh-agent` (sans commande) | Affiche la même chose que `status` |
| `h42-mesh-agent connection …` | Définit les connexions internet dans la configuration locale (voir ci-dessous) |

### Commande `connection`

Définit, dans la configuration locale, les réglages d'une connexion internet propres à la machine, sans éditer le fichier à la main.

| Sous-commande (*proposition*) | Rôle |
| --- | --- |
| `connection list` | Liste les connexions du routeur connues du contrôleur (numéro, nom, rôle) et leurs réglages locaux ; signale celles qui ne sont pas encore définies |
| `connection show c0` | Affiche les réglages locaux d'une connexion |
| `connection set c0 --interface eth1 --vrf wan0 [options]` | Crée ou modifie les réglages locaux d'une connexion |
| `connection remove c0` | Supprime les réglages locaux d'une connexion |

Options de `set` : `--interface` et `--vrf` (obligatoires à la création), `--ports 42000-42999`, `--force-ipv4 …`, `--force-ipv6 …`, `--fallback-delay 30s`, `--ipv6-retry 10m` (et les options correspondantes pour effacer un réglage).

Fonctionnement (*proposition*) :

- la connexion est désignée par son numéro (`c0`…`c9`), plus simple à saisir que son UID ; l'agent retrouve l'UID dans la configuration reçue du contrôleur et c'est l'UID qui est enregistré dans le fichier. Il accepte aussi directement un UID ;
- l'agent vérifie avant d'écrire : l'interface existe, la VRF existe (elle est créée par la configuration du système), l'interface est rattachée à cette VRF, la plage de ports et les adresses sont valides ;
- il modifie le fichier en conservant sa mise en forme et ses commentaires (par exemple avec la bibliothèque tomlkit, licence MIT) ;
- le service en cours d'exécution prend la modification en compte sans redémarrage (signal de rechargement ou prochain passage de la boucle).

### Commande `status`

Premier outil de diagnostic sur un routeur : elle doit répondre d'un coup d'œil à « est-ce que ça marche, et sinon où ? ».

Contenu (*proposition*) :

- **Identité** : maillage, site (nom, quadrigramme, AS), numéro du routeur, identifiant du routeur ;
- **Agent** : service actif ou non, date de la dernière boucle, empreinte et date de la dernière configuration appliquée, erreurs de la dernière boucle ;
- **Contrôleur** : contrôleur joint (premier ou second), connexion utilisée, date du dernier échange réussi ;
- **Connexions** : numéro, rôle, interface, VRF (présente ou non), adresses publiques ;
- **Tunnels** : nom d'interface, site et connexion distants, côté (`a`/`b`), rôle, famille utilisée, dernière poignée de main, état de la session BGP ;
- **Lien interne** (site à deux routeurs) : état de la session iBGP.

Fonctionnement (*proposition*) :

- la boucle `run` écrit à chaque passage un état résumé dans un fichier (par exemple `/run/h42-mesh/status.json`) ; `status` le lit et le complète par des lectures directes (`wg show`, `vtysh … json`) ;
- si le fichier est trop ancien ou absent, `status` l'indique clairement (service arrêté ou bloqué) et affiche ce qu'il peut lire directement ;
- option `--json` pour une sortie lisible par un programme ;
- code de retour non nul en cas de problème (service arrêté, contrôleur injoignable depuis longtemps, tunnel hors service), utilisable par une supervision.

## Configuration locale

*Proposition* : fichier `/etc/h42-mesh/agent.toml` (TOML, lisible et commenté). Contenu décidé :

| Élément | Remarque |
| --- | --- |
| Adresses des deux contrôleurs | L'agent bascule sur la seconde si la première ne répond pas |
| Numéro du maillage | 0 par défaut |
| Serveurs DNS du client intégré | Par défaut `1.1.1.1`, `2606:4700:4700::1111` (Cloudflare), `8.8.8.8` et `2001:4860:4860::8888` (Google) |
| Lien interne (site à deux routeurs) | Nom de l'interface et adresse fe80:: de l'autre routeur |
| Par connexion, désignée par son UID : | |
| — interface physique et VRF | Obligatoires ; la VRF est créée par la configuration du système, pas par l'agent |
| — plage de ports | Facultative, vaut pour IPv4 et IPv6 (IPv4 partagée, ports ouverts par la box) |
| — adresse IPv4 et/ou IPv6 forcée | Facultative (machine à la fois routeur et contrôleur) |
| — délais du repli IPv6 → IPv4 | 30 s et 10 min par défaut |

Les clés privées (Ed25519 de l'agent, X25519 de chaque tunnel) sont stockées à part, lisibles par root uniquement (*proposition* : `/var/lib/h42-mesh/`).

### Validation par Pydantic

La configuration locale est lue puis validée par des modèles **Pydantic**, comme les schémas de l'API du contrôleur. Une configuration invalide est refusée avec un message qui indique le champ en cause, au démarrage de `run` comme lors d'une modification par `connection set`. Les modèles interdisent les champs inconnus (`extra="forbid"`) : une faute de frappe dans un nom de réglage est signalée au lieu d'être ignorée.

Exemple de fichier :

```toml
# /etc/h42-mesh/agent.toml
controllers = ["https://vps1.example.org", "https://vps2.example.org"]
mesh_number = 0
# dns_servers = ["1.1.1.1", "2606:4700:4700::1111", "8.8.8.8", "2001:4860:4860::8888"]

[internal_link]                     # seulement sur un site à deux routeurs
interface = "eth2"
peer_link_local = "fe80::1a2b:3cff:fe4d:5e6f"

[[connections]]
uid = "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f"   # c0, fibre
interface = "eth1"
vrf = "wan0"

[[connections]]
uid = "0b9e8d7c-6a5f-4e3d-2c1b-0a9f8e7d6c5b"   # c1, 4G
interface = "wwan0"
vrf = "wan1"
fallback_delay = 30      # secondes
ipv6_retry = 600         # secondes
```

Modèles (noms du code, en anglais) :

**`AgentConfig`** — fichier complet

| Champ | Type | Défaut | Règles de validation |
| --- | --- | --- | --- |
| `controllers` | liste d'URL HTTPS | — | 1 ou 2 adresses, `https` uniquement, sans doublon |
| `mesh_number` | entier | `0` | 0 à 9 |
| `dns_servers` | liste d'adresses IP | les 4 serveurs par défaut | au moins une adresse ; IPv4 ou IPv6 |
| `state_dir` | chemin | `/var/lib/h42-mesh` | chemin absolu |
| `internal_link` | `InternalLink` | absent | facultatif |
| `connections` | liste de `ConnectionSettings` | liste vide | UID, interfaces et VRF tous différents d'une connexion à l'autre |

**`InternalLink`** — lien interne d'un site à deux routeurs

| Champ | Type | Règles de validation |
| --- | --- | --- |
| `interface` | texte | nom d'interface Linux valide (15 caractères au plus) |
| `peer_link_local` | adresse IPv6 | dans `fe80::/10` |

**`ConnectionSettings`** — réglages locaux d'une connexion

| Champ | Type | Défaut | Règles de validation |
| --- | --- | --- | --- |
| `uid` | UUID | — | UID de la connexion dans le contrôleur |
| `interface` | texte | — | nom d'interface Linux valide |
| `vrf` | texte | — | nom de VRF Linux valide, différent de la VRF par défaut |
| `ports` | `PortRange` | absent | facultatif ; vaut pour IPv4 et IPv6, un tunnel écoutant sur le même port dans les deux familles |
| `force_ipv4` | adresse IPv4 | absent | adresse publique (ni privée, ni locale au lien, ni de boucle locale) |
| `force_ipv6` | adresse IPv6 | absent | adresse globale (ni ULA, ni locale au lien) |
| `fallback_delay` | entier (secondes) | `30` | 5 à 3600 |
| `ipv6_retry` | entier (secondes) | `600` | 60 à 86400 |

**`PortRange`** — plage de ports d'une connexion

| Champ | Type | Règles de validation |
| --- | --- | --- |
| `min`, `max` | entiers | 1 à 65535, `min` ≤ `max` |

Deux types de vérification sont distingués :

- **validation statique**, par Pydantic, sur le fichier seul : types, formats, bornes, doublons ;
- **vérification de cohérence**, par l'agent, avec le système et le contrôleur : l'interface et la VRF existent, l'interface est rattachée à la VRF, chaque UID correspond à une connexion du routeur, la plage de ports de la connexion recoupe la plage du routeur (`42000 + 2000 × maillage + 1000 × numéro du routeur`). Ces vérifications ne peuvent pas être faites par Pydantic seul, car elles dépendent de l'état de la machine.

Les autres données de l'agent sont aussi décrites par des modèles Pydantic : le fichier d'état lu par `status` (`/run/h42-mesh/status.json`) et les messages échangés avec le contrôleur.

## Organisation en processus

L'agent n'est pas un processus unique : il a **une instance par connexion internet**, qui gère en sous-processus les wireguard-go des tunnels de cette connexion.

| Processus | VRF | Rôle |
| --- | --- | --- |
| **Processus principal** | par défaut | Lit la configuration locale, lance et surveille les instances de connexion, génère la configuration de FRR et de keepalived, règle le système, lit la table BGP, écrit l'état lu par `status` |
| **Instance de connexion** (une par connexion) | celle de la connexion | Lancée dans la VRF de sa connexion (`ip vrf exec`) ; reconnaissance des adresses publiques de la connexion ; crée, met à jour, supprime et surveille les processus wireguard-go de ses tunnels (redémarrage s'ils s'arrêtent) |
| **wireguard-go** (un par tunnel) | celle de la connexion | Sous-processus de l'instance de connexion |

Avantages :

- un processus lancé par `ip vrf exec` est rattaché à la VRF, et ses sous-processus en héritent : les wireguard-go d'une connexion sont automatiquement dans la bonne VRF, comme les requêtes DNS et HTTPS de l'instance, sans réglage socket par socket ;
- une panne ou un blocage sur une connexion (par exemple une 4G instable) n'affecte que son instance, pas les autres connexions ni le processus principal ;
- la supervision des wireguard-go est assurée par l'instance de leur connexion.

*Propositions* :

- les instances de connexion sont des **processus enfants du processus principal** (une seule unité systemd, `h42-mesh-agent.service`), lancés par `ip vrf exec <vrf> h42-mesh-agent connection-worker <uid>` ; le processus principal les relance s'ils s'arrêtent. L'unité systemd a besoin de `Delegate=yes`, car `ip vrf exec` crée un sous-groupe de contrôle (*cgroup*) : à vérifier par le prototype ;
- les processus communiquent par une socket Unix locale (non concernée par les VRF) ;
- les échanges avec le contrôleur passent par les instances de connexion, déjà dans leur VRF : le processus principal confie ses requêtes à l'instance de la meilleure connexion disponible (actives d'abord, par priorité, puis secours) et passe à la suivante en cas d'échec ;
- le module de gestion de WireGuard (voir ci-dessous) est utilisé par les instances de connexion.

## Récupération et stockage de la configuration

La configuration voulue du routeur (son site, ses connexions et ses tunnels, avec clés publiques, PSK, adresses et ports des autres extrémités) est récupérée auprès du contrôleur puis **stockée localement**. C'est ce stockage qui permet de respecter le principe « si le contrôleur est injoignable, les tunnels continuent de fonctionner », y compris après un redémarrage du routeur.

### Récupération (*proposition*)

- Le processus principal interroge le contrôleur à intervalle régulier (par exemple toutes les 30 secondes, avec un léger décalage aléatoire pour que tous les routeurs n'interrogent pas en même temps), par l'intermédiaire de l'instance de la meilleure connexion disponible. Le contrôleur ne peut pas joindre lui-même les routeurs, souvent derrière un NAT : c'est toujours l'agent qui demande.
- La réponse porte une **empreinte** de la configuration. L'agent envoie l'empreinte de celle qu'il a déjà (en-tête HTTP `If-None-Match`) ; si rien n'a changé, le contrôleur répond « non modifié » (code 304), sans renvoyer la configuration.
- La nouvelle configuration est validée par les modèles Pydantic de l'agent avant d'être stockée ou appliquée ; une configuration invalide est refusée, et la précédente reste en place.

### Stockage

Dans le dossier d'état de l'agent (`state_dir`, `/var/lib/h42-mesh` par défaut), lisible par root uniquement (droits `0600`), car il contient les PSK et les clés privées :

| Fichier (*proposition*) | Contenu |
| --- | --- |
| `config.json` | Dernière configuration valide reçue du contrôleur, avec son empreinte, sa date de réception et le contrôleur qui l'a fournie |
| `config.previous.json` | La configuration précédente, pour revenir en arrière si la nouvelle ne peut pas être appliquée |
| `tunnels/<uid du tunnel>.json` | État local de chaque tunnel : clé privée X25519, port choisi, et si le contrôleur a bien enregistré la clé publique et le port |
| `agent.key` | Clé privée Ed25519 de l'agent |

- **Écriture sûre** : chaque fichier est écrit dans un fichier temporaire, synchronisé sur le disque, puis renommé à la place de l'ancien. Une coupure de courant pendant l'écriture laisse donc l'ancienne version intacte, jamais un fichier à moitié écrit.
- **Au démarrage** : l'agent applique d'abord `config.json`, puis interroge le contrôleur. Les tunnels se rétablissent ainsi dès le démarrage, même si le contrôleur est injoignable.
- **Durée de validité** : la configuration stockée reste appliquée tant qu'aucune nouvelle n'est reçue, sans limite de durée.
- **Clés et ports des tunnels** : la clé privée et le port d'un tunnel sont conservés tant que le tunnel existe dans la configuration, et réutilisés à chaque redémarrage ; ils ne sont supprimés qu'avec le tunnel.

### Distribution aux instances de connexion

Le processus principal est le seul à lire et écrire ces fichiers. Il transmet à chaque instance de connexion, par la socket Unix locale, la partie de la configuration qui la concerne : ses tunnels, avec leurs clés et leurs ports. Les instances ne stockent rien elles-mêmes.

`status` affiche l'empreinte et la date de la configuration appliquée, et depuis quand le contrôleur n'a pas été joint.

## Boucle principale

1. Lire la configuration voulue auprès du contrôleur (ou garder la dernière s'il est injoignable).
2. Pour chaque connexion : lancer son instance si elle ne tourne pas ; vérifier que sa VRF existe et que l'interface y est rattachée (sinon, signaler une erreur sans rien créer), relever sa passerelle, lancer la reconnaissance des adresses publiques depuis cette VRF.
3. Pour chaque tunnel voulu (étapes réalisées par l'instance de la connexion locale du tunnel) :
   - générer la paire de clés X25519 si elle n'existe pas, choisir un port libre dans la plage du routeur (`42000 + 2000 × maillage + 1000 × numéro du routeur`, intersection avec la plage de la connexion), et les remonter ;
   - lancer ou mettre à jour le processus wireguard-go dans la VRF de la connexion (`ip vrf exec`), interface `wd<maillage>c<locale><quadrigramme distant>r<routeur distant>c<distante>` dans la VRF par défaut ;
   - configurer le pair (`AllowedIPs` 0.0.0.0/0 et ::/0, PSK, adresse et port de l'autre extrémité côté `b`, keepalive 25 s côté `b`), les adresses de la paire IPv4 (169.254) et de la paire IPv6 locale au lien (`fe80::a9fe:…`) ;
   - côté `b`, gérer le repli IPv6 → IPv4 selon les délais de la connexion.
4. Supprimer, par l'instance de connexion concernée, les tunnels qui ne sont plus voulus (arrêt du processus, suppression de l'interface et des clés).
5. Générer la configuration de FRR (Jinja2) : session eBGP par tunnel sur fe80::, `extended-nexthop`, BFD ou temporisations lentes selon le rôle, communauté « secours », `redistribute connected` filtré, session iBGP sur le lien interne ; recharger FRR seulement si elle a changé.
6. Générer la configuration de keepalived sur un site de maison à deux routeurs.
7. Réglages système : `rp_filter` souple sur les tunnels, réservation de la plage de ports (`net.ipv4.ip_local_reserved_ports`).
8. Remonter l'état des tunnels et la table BGP (lue avec `vtysh … json`).

## Isolation de la gestion de WireGuard

Toute la gestion des tunnels WireGuard passe par un **module dédié** (*backend* de tunnel), derrière une interface simple :

| Opération | Rôle |
| --- | --- |
| créer un tunnel | interface, clés, PSK, pair, adresses, rattachement à la VRF de la connexion |
| mettre à jour un tunnel | pair, adresse et port distants, repli IPv6 → IPv4 |
| supprimer un tunnel | arrêt du processus, suppression de l'interface |
| lire l'état | dernière poignée de main, famille utilisée, compteurs |
| lister les tunnels existants | pour comparer l'état réel à l'état voulu |

Le reste de l'agent (boucle de réconciliation, FRR, remontées) ne connaît que cette interface et ne sait pas quelle implémentation est utilisée. Première implémentation : wireguard-go. Si le test de performances (voir [todo.md](../todo.md)) montre qu'il ne convient pas, seule une autre implémentation de ce module est à écrire (par exemple le module du noyau dans un espace de noms réseau par connexion).

## Échanges avec le contrôleur

- Toutes les requêtes (configuration, remontées, reconnaissance des adresses) partent de la VRF d'une connexion internet, en essayant d'abord les connexions actives par ordre de priorité, puis les connexions de secours. Elles sont émises par l'instance de la connexion, qui est déjà dans sa VRF (voir « Organisation en processus »). La reconnaissance des adresses d'une connexion est toujours faite par sa propre instance.
- **Client DNS intégré** : le nom des contrôleurs est résolu par l'agent lui-même, en interrogeant les serveurs DNS depuis la VRF de la connexion, sans la résolution du système. Serveurs interrogés : `1.1.1.1`, `2606:4700:4700::1111` (Cloudflare), `8.8.8.8` et `2001:4860:4860::8888` (Google) par défaut, modifiables dans la configuration locale ; seuls ceux de la famille disponible sur la connexion sont utilisés. *Proposition* : bibliothèque dnspython (licence ISC).
- La connexion HTTPS est établie vers l'adresse obtenue, en vérifiant le certificat pour le nom du contrôleur (indication du nom, SNI).
- Si le premier contrôleur ne répond pas, l'agent essaie le second.
- **Modèles des messages** : pas de paquet commun avec le contrôleur. L'agent a sa propre copie des modèles Pydantic des messages, adaptée à ses besoins (il peut n'en garder que les champs qu'il utilise). La référence reste la description OpenAPI du contrôleur.
  - Les modèles des réponses du contrôleur ignorent les champs inconnus (`extra="ignore"`), pour qu'un contrôleur plus récent qui ajoute un champ ne casse pas un agent plus ancien. À l'inverse, la configuration locale refuse les champs inconnus.
  - *Proposition* : un test de l'agent compare ses modèles à la description OpenAPI du contrôleur (fichier exporté dans le dépôt), pour détecter un écart avant la mise en service.

## Outils pilotés

| Outil | Usage | Licence |
| --- | --- | --- |
| wireguard-go | Un processus par tunnel | MIT |
| `wg` (wireguard-tools) | Configuration des tunnels, appelé comme programme séparé | GPL, non intégré |
| FRR (`vtysh`) | BGP, BFD | GPL, non intégré |
| keepalived | VRRP | GPL, non intégré |
| pyroute2 | Interfaces, adresses, VRF | Apache 2.0 / GPL (double licence) |
| dnspython (*proposition*) | Client DNS intégré | ISC |

## Tests

pytest. *Proposition* : le calcul de l'état voulu (fichiers FRR, liste des interfaces et de leurs réglages) est séparé de son application, et testé sans privilèges ; l'application est testée dans un espace de noms réseau (*netns*) en intégration.

## Points ouverts


- Accès à Internet du routeur lui-même : confié à une application tierce (voir [todo.md](../todo.md)) ; prérequis : heure synchronisée.
- Performances de wireguard-go : test prévu sur Raspberry Pi 5 et sur un pare-feu x86 (voir [todo.md](../todo.md)).
