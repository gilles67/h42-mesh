# h42-mesh — à faire

Sujets reportés, à reprendre plus tard. Chaque entrée dit ce qui était prévu et pourquoi c'est reporté.

## Connexions facturées au volume

- **Prévu jusqu'ici** : un attribut « facturée au volume » (`metered`) sur chaque connexion, qui réduisait les sondes (temporisations BGP lentes, sans BFD, comme un tunnel de secours) et limitait les tunnels directs aux sites qui en ont besoin.
- **Décision** : retiré du modèle de données ; le besoin sera défini plus tard, d'une façon un peu différente.
- **À définir** : comment déclarer ce caractère (attribut de la connexion, configuration locale de l'agent, autre), et ses effets sur les tunnels, la détection de panne et le transit.

## Agent dans plusieurs maillages et sur plusieurs contrôleurs

- **Première version** : un agent ne rejoint qu'un seul maillage, sur un seul contrôleur. Son numéro de maillage vaut 0 par défaut.
- **Plus tard** : un même agent pourra rejoindre plusieurs maillages, éventuellement pilotés par des contrôleurs différents. Ce qui est déjà prévu dans `architecture.md` :
  - la machine est déclarée et enrôlée comme routeur dans chaque maillage ;
  - chaque maillage a un numéro local à l'agent (0 à 9, unique sur la machine), qui figure dans le nom des interfaces de tunnel et dans le calcul de la plage de ports (`42000 + 2000 × maillage + 1000 × numéro du routeur`) ;
  - le premier maillage utilise la table de routage principale, chaque maillage supplémentaire une VRF définie dans la configuration locale de l'agent, avec ses interfaces de tunnel et son instance BGP.
- **À définir** :
  - la forme de la configuration locale : une liste d'appartenances (contrôleur, maillage, numéro, VRF, clés) ;
  - les clés de signature et l'enrôlement par appartenance ;
  - la découverte des adresses publiques et la supervision (tunnels, routes BGP) envoyées à plusieurs contrôleurs ;
  - le cas d'une même connexion physique utilisée par plusieurs maillages.

## Application pare-feu

- **Première version** : pas d'échange avec l'application pare-feu. FRR annonce les réseaux connectés de la VRF par défaut, filtrés par l'agent.
- **Plus tard** : définir l'interface avec l'application pare-feu (réseaux à annoncer, sens et format des échanges), en même temps que la conception de cette application.

## Accès à Internet depuis la VRF par défaut

- **Constat** : les interfaces des connexions internet sont dans des VRF dédiées ; la VRF par défaut (réseau local, tunnels, BGP) n'a pas de route vers Internet.
- **Décision** : ce projet ne le traite pas ; la tâche est confiée à une application tierce, qui reste à choisir ou à concevoir (solution technique pas encore trouvée).
- **À couvrir** : mises à jour, DNS et NTP du routeur lui-même ; accès à Internet des appareils du réseau local (en lien avec l'application pare-feu).
- **Prérequis pour h42-mesh** : l'heure du routeur doit être synchronisée (JWT valables environ une minute).

## Test de performances de wireguard-go

- **Pourquoi** : wireguard-go fonctionne en espace utilisateur, avec un processus par tunnel lancé dans la VRF de sa connexion. Il est en général moins rapide que le module du noyau ; il faut vérifier, avant d'aller loin dans l'agent, que les performances suffisent sur du matériel modeste.
- **Matériel de test** :
  - Raspberry Pi 5, 8 Go (arm64) ;
  - un pare-feu x86 d'entrée de gamme, par exemple un Sophos XG 106 Rev1, sous Debian 13.
- **À mesurer** :
  - débit d'un tunnel (iperf3, TCP et UDP), en IPv4 et en IPv6, comparé au module WireGuard du noyau sur le même matériel ;
  - charge processeur et mémoire par processus wireguard-go ;
  - comportement avec de nombreux tunnels simultanés (par exemple 20 à 40 processus) ;
  - latence et gigue ;
  - montage complet : processus lancé avec `ip vrf exec` dans la VRF d'une connexion, interface dans la VRF par défaut.
- **Si les résultats sont insuffisants** : revoir le choix du plan de données (par exemple le module du noyau avec un espace de noms réseau par connexion, ou une autre implémentation en espace utilisateur).
