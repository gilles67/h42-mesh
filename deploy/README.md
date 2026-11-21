# Déploiement du contrôleur sur un VPS

Ce dossier contient de quoi installer le **contrôleur** h42-mesh sur un VPS Debian 13, derrière **Traefik**, en conteneurs Podman sans privilèges (*rootless*) gérés par systemd grâce à **Quadlet**. L'interface web n'est pas encore déployée ; elle s'ajoutera plus tard derrière le même Traefik (voir « Limites actuelles »).

| Élément | Où | Rôle |
| --- | --- | --- |
| Traefik | Conteneur, réseau de l'hôte | Seul point d'entrée HTTPS (ports 80 et 443), certificats Let's Encrypt ; `/api` vers le contrôleur |
| Contrôleur | Conteneur, réseau de l'hôte, `127.0.0.1:8000` | API ; base SQLite dans un volume |
| geoipupdate | Conteneur lancé par un minuteur | Télécharge la base GeoLite2 ASN de MaxMind (facultatif) |
| Agent, wireguard-go, FRR | Hôte | Hors de ce dossier (le VPS est aussi un routeur) |

## Contenu du dossier

```
deploy/
├── controller/Containerfile          image du contrôleur
├── quadlet/                          unités Quadlet (~/.config/containers/systemd/)
│   ├── h42-mesh-controller.container
│   ├── traefik.container
│   ├── geoipupdate.container
│   ├── h42-mesh-data.volume          base SQLite
│   ├── h42-mesh-geoip.volume         base GeoLite2 ASN
│   └── traefik-acme.volume           certificats Let's Encrypt
├── systemd/geoipupdate.timer         mise à jour GeoLite2 deux fois par semaine
├── traefik/traefik.yml               configuration statique de Traefik
├── traefik/dynamic/h42-mesh.yml      routes (configuration dynamique)
├── config/*.env.example              réglages à copier et adapter
└── sysctl/90-h42-mesh-rootless-ports.conf
```

## Choix de mise en œuvre

- **Rootless** : les conteneurs tournent sous un utilisateur dédié `h42mesh`, sans droits root. Pour que Traefik écoute sur les ports 80 et 443, un réglage système abaisse le premier port non privilégié à 80.
- **Réseau de l'hôte** pour Traefik et le contrôleur : la reconnaissance des adresses publiques des agents repose sur l'adresse source vue par le contrôleur. Sur le réseau de l'hôte, Traefik voit la vraie adresse du client et la transmet dans `X-Forwarded-For`. Le contrôleur n'écoute que sur `127.0.0.1:8000` et ne fait confiance à cet en-tête que s'il vient de `127.0.0.1` ou `::1` (`H42_MESH_TRUSTED_PROXIES`).
- **Socket Podman non exposé** : Traefik est configuré uniquement par fichiers (`traefik.yml` et `dynamic/`), sans accès à Podman.
- **Aucun secret dans l'image ni dans le dépôt** : la phrase secrète est un secret Podman, monté en lecture seule pour l'utilisateur du conteneur ; la clé de licence MaxMind aussi.
- **Migrations** : appliquées par le contrôleur à chaque démarrage.
- **Conteneurs durcis** : système de fichiers en lecture seule, aucune capacité, `no-new-privileges`.

## Installation pas à pas

Les commandes précédées de `#` se lancent en root, celles précédées de `$` sous l'utilisateur `h42mesh`. Remplacer `vps1.example.org` par le nom du VPS.

### 1. Prérequis

- Debian 13 à jour, avec une IPv4 et une IPv6 publiques.
- Enregistrements DNS **A** et **AAAA** de `vps1.example.org` pointant vers le VPS (nécessaire à Let's Encrypt).
- Ports **80** et **443** ouverts en entrée (TCP), en IPv4 et en IPv6, dans le pare-feu de l'hébergeur et celui du VPS.

### 2. Paquets

```
# apt install podman passt uidmap dbus-user-session systemd-container git
```

Debian 13 fournit Podman 5, qui comprend Quadlet ; `passt` fournit le réseau des conteneurs rootless, `systemd-container` la commande `machinectl`.

### 3. Utilisateur dédié

```
# adduser --disabled-password --gecos "" h42mesh
# loginctl enable-linger h42mesh
```

`adduser` attribue à l'utilisateur ses plages d'identifiants subordonnés (`/etc/subuid`, `/etc/subgid`), indispensables au rootless ; `enable-linger` fait démarrer ses services au démarrage du VPS, sans session ouverte.

### 4. Ports 80 et 443 pour un utilisateur sans privilèges

```
# printf 'net.ipv4.ip_unprivileged_port_start = 80\n' \
      > /etc/sysctl.d/90-h42-mesh-rootless-ports.conf
# sysctl --system
```

C'est le contenu de `deploy/sysctl/90-h42-mesh-rootless-ports.conf` (le dépôt n'est cloné qu'à l'étape suivante).

### 5. Session de l'utilisateur et dépôt

Ouvrir une vraie session systemd de l'utilisateur (nécessaire à `systemctl --user` ; `su` ou `sudo -u` ne suffisent pas) :

```
# machinectl shell h42mesh@
$ git clone https://…/h42-mesh.git ~/h42-mesh
$ cd ~/h42-mesh
```

### 6. Image du contrôleur

```
$ podman build -t localhost/h42-mesh-controller:latest \
      -f deploy/controller/Containerfile controller/
```

### 7. Phrase secrète

Elle chiffre les secrets stockés en base (PSK des tunnels, secrets TOTP). **Sans elle, ils sont perdus** : il faudrait régénérer toutes les PSK et réenregistrer toutes les doubles authentifications. La sauvegarder à part (gestionnaire de mots de passe) avant de continuer.

```
$ head -c 48 /dev/urandom | base64 -w0 > ~/passphrase.tmp
$ cat ~/passphrase.tmp        # à recopier dans le gestionnaire de mots de passe
$ podman secret create h42-mesh-passphrase ~/passphrase.tmp
$ shred -u ~/passphrase.tmp
```

Le deuxième contrôleur (étape 6 de la feuille de route) devra utiliser **la même** phrase secrète.

### 8. Configuration

```
$ mkdir -p ~/.config/h42-mesh/traefik/dynamic
$ cp deploy/config/controller.env.example ~/.config/h42-mesh/controller.env
$ cp deploy/config/traefik.env.example    ~/.config/h42-mesh/traefik.env
$ cp deploy/config/geoipupdate.env.example ~/.config/h42-mesh/geoipupdate.env
$ cp deploy/traefik/traefik.yml ~/.config/h42-mesh/traefik/
$ cp deploy/traefik/dynamic/h42-mesh.yml ~/.config/h42-mesh/traefik/dynamic/
```

À adapter :

- `~/.config/h42-mesh/traefik.env` : `H42_MESH_DOMAIN=vps1.example.org` ;
- `~/.config/h42-mesh/traefik/traefik.yml` : l'adresse e-mail Let's Encrypt (`email:`). Pour les premiers essais, décommenter `caServer` (autorité de test) afin de ne pas atteindre les limites de Let's Encrypt, puis le recommenter et supprimer le volume `traefik-acme` une fois tout validé ;
- `~/.config/h42-mesh/controller.env` : en général rien ; `H42_MESH_AGENT_JWT_AUDIENCE` doit correspondre à la configuration des agents.

### 9. Unités Quadlet

```
$ mkdir -p ~/.config/containers/systemd ~/.config/systemd/user
$ cp deploy/quadlet/* ~/.config/containers/systemd/
$ cp deploy/systemd/geoipupdate.timer ~/.config/systemd/user/
$ systemctl --user daemon-reload
```

Quadlet génère alors les services `h42-mesh-controller.service`, `traefik.service` et `geoipupdate.service`, ainsi que les volumes. Pour vérifier les fichiers en cas d'erreur :

```
$ /usr/libexec/podman/quadlet -dryrun -user
```

### 10. Base GeoLite2 ASN (facultatif)

Sans elle, le champ « opérateur » des connexions reste vide ; tout le reste fonctionne.

1. Créer un compte gratuit sur <https://www.maxmind.com/en/geolite2/signup> et une clé de licence.
2. Renseigner `GEOIPUPDATE_ACCOUNT_ID` dans `~/.config/h42-mesh/geoipupdate.env`.
3. Enregistrer la clé comme secret et lancer un premier téléchargement :

```
$ printf '%s' 'LA_CLE_DE_LICENCE' | podman secret create geoipupdate-license-key -
$ systemctl --user start geoipupdate.service
$ systemctl --user enable --now geoipupdate.timer
```

La base est mise à jour deux fois par semaine ; le contrôleur relit le fichier quand il change, sans redémarrage. La licence GeoLite2 impose de citer MaxMind : « This product includes GeoLite2 data created by MaxMind, available from https://www.maxmind.com ».

### 11. Démarrage

```
$ systemctl --user start h42-mesh-controller.service traefik.service
$ systemctl --user status h42-mesh-controller.service traefik.service
```

Les deux services démarrent ensuite seuls à chaque démarrage du VPS (`WantedBy=default.target` et `enable-linger`).

### 12. Compte administrateur

Au premier démarrage, le contrôleur crée le compte `admin` avec un mot de passe aléatoire, écrit **une seule fois** dans son journal :

```
$ podman logs h42-mesh-controller 2>&1 | grep "administrator created"
```

À la première connexion, l'interface (ou l'API) impose de changer ce mot de passe et d'enregistrer la double authentification TOTP. Le mot de passe initial reste dans le journal, mais ne sert plus une fois changé.

### 13. Vérification

```
$ curl https://vps1.example.org/api/v1/health
{"status":"ok","version":"0.1.0"}
```

La documentation de l'API est servie sur `https://vps1.example.org/api/v1/docs`.

## Exploitation

### Mise à jour du contrôleur

```
$ cd ~/h42-mesh && git pull
$ podman build -t localhost/h42-mesh-controller:latest -f deploy/controller/Containerfile controller/
$ systemctl --user restart h42-mesh-controller.service
```

Les migrations éventuelles sont appliquées au redémarrage. Faire une sauvegarde de la base avant (ci-dessous). Si les fichiers de `deploy/` ont changé, recopier ceux qui sont concernés puis lancer `systemctl --user daemon-reload`.

### Sauvegarde

À sauvegarder régulièrement, hors du VPS :

- la base SQLite :

  ```
  $ systemctl --user stop h42-mesh-controller.service
  $ podman volume export h42-mesh-data --output ~/h42-mesh-data-$(date +%F).tar
  $ systemctl --user start h42-mesh-controller.service
  ```

- la phrase secrète, conservée à part (étape 7) : une sauvegarde de la base sans elle ne permet pas de relire les PSK ni les secrets TOTP ;
- les fichiers de `~/.config/h42-mesh/`.

Le volume `traefik-acme` n'a pas besoin d'être sauvegardé : les certificats sont redemandés à Let's Encrypt.

### Journaux

```
$ podman logs -f h42-mesh-controller
$ podman logs -f traefik
$ journalctl --user -u h42-mesh-controller -f    # si le journal persistant est activé
```

## Question ouverte : services dans la VRF de la connexion

> **Non traitée ici.** Voir « Questions ouvertes » dans [docs/architecture.md](../docs/architecture.md).

Ce VPS est aussi un routeur du maillage : son interface publique doit alors être placée dans une **VRF dédiée** (règle de l'architecture), alors que Traefik, le contrôleur et SSH écoutent dans la **VRF par défaut**. Tant que la question n'est pas tranchée, ils ne recevront pas les connexions arrivant par l'interface publique une fois celle-ci déplacée dans sa VRF. Deux pistes restent à évaluer :

1. lancer ces services dans la VRF de la connexion (`ip vrf exec`, ou une unité systemd dans cette VRF) ;
2. les laisser dans la VRF par défaut et accepter les connexions arrivant par une VRF (`net.ipv4.tcp_l3mdev_accept=1`, et l'équivalent UDP si besoin).

En attendant, la procédure ci-dessus s'applique à un VPS dont l'interface publique est encore dans la VRF par défaut (avant l'installation de l'agent), ou à un VPS qui n'est que contrôleur.

## Limites actuelles

- **Interface web** : pas encore déployée ; Traefik ne route que `/api`. Elle s'ajoutera comme un conteneur de fichiers statiques, routé sur `/`.
- **Un seul contrôleur** : le deuxième VPS, la base PostgreSQL répliquée et la haute disponibilité arrivent à l'étape 6 de la feuille de route.
- **Image construite sur le VPS** : pas encore de registre d'images ni de construction automatique.
- **Version de Traefik** : fixée à la branche `v3.3` dans `traefik.container` ; la faire évoluer après lecture des notes de version.
