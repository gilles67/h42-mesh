# Spécification — interface graphique (`gui/`)

> **Statut : brouillon.** Ce fichier détaille, pour l'interface, les décisions de [architecture.md](../architecture.md), qui reste la référence. Ce qui n'y figure pas encore est marqué *proposition*.

## Rôle

Application web monopage, simple client de l'API du contrôleur. Elle ne contient aucune logique métier : les tunnels, droits et validations sont décidés par le contrôleur.

## Technologies

TypeScript (mode strict), React, Vite, Mantine (composants), TanStack Query (appels à l'API et cache), React Flow (topologie). Compilée en fichiers statiques servis par un conteneur léger ; aucun serveur Node.js en production.

- **Client API** : généré depuis la description OpenAPI du contrôleur, jamais écrit à la main.
  - **openapi-typescript** (MIT) produit les types (`src/api/schema.d.ts`, versionné ; `npm run api:check` vérifie qu'il est à jour).
  - **openapi-fetch** (MIT) fait les appels, vérifiés par ces types, avec le cookie de session (`credentials: "include"`).
  - **openapi-react-query** (MIT) les relie à TanStack Query.
- **Langue** : anglais. Tous les textes passent par le mécanisme de traduction, y compris l'affichage des valeurs de l'API (`active`, `backup`…), pour pouvoir traduire l'interface plus tard.
  - Bibliothèques : i18next et react-i18next, avec les textes dans `src/i18n/en.json`.
  - Les clés sont typées : une clé inconnue est une erreur de compilation.
  - La règle ESLint `i18next/no-literal-string` refuse tout texte écrit en dur dans un composant.
- **Développement** : `npm run dev` ; le serveur de Vite redirige `/api` vers le contrôleur local. La page et l'API ont donc la même origine, comme en production derrière Traefik, et le cookie de session fonctionne.
- **Tests** : Vitest, Testing Library et jsdom ; les réponses de l'API sont simulées.

## Écrans (*proposition*)

| Écran | Contenu | Droit |
| --- | --- | --- |
| Connexion | Mot de passe, puis code TOTP ; changement de mot de passe et enregistrement TOTP à la première connexion | — |
| Maillages | Liste des maillages accessibles ; création si autorisé | — |
| Topologie d'un maillage | Graphe React Flow : sites, routeurs, tunnels colorés selon leur état (établi, secours, hors service) | `read` |
| Sites et routeurs | Liste et fiche : quadrigramme, AS, emplacement ; routeurs, dernier contact, révocation | `read` / `manage` |
| Connexions | Rôle, priorité, connexion directe, description, opérateur, adresses publiques | `read` / `manage` |
| Enrôlement | Création d'un routeur et de son jeton, affiché une seule fois avec la commande à lancer | `manage` |
| Tunnels | Liste : extrémités, rôle, famille utilisée, dernière poignée de main, session BGP | `read` |
| Routes BGP | Table d'un routeur : préfixe, site d'origine, chemin AS, meilleure route, secours ; date du relevé | `read` |
| Accès | Utilisateurs ayant accès au maillage, niveau `manage` / `read` | `manage` |
| Utilisateurs | Création, droit de créer des maillages | administrateur |

En lecture seule, les écrans sont les mêmes, sans les boutons de modification.

## Authentification (implémentée dans `src/auth/`)

- **Garde (`AuthGate`)** : il choisit l'écran d'après `GET /api/v1/auth/me` (`next_step`).
  - Personne n'est connecté : écran de connexion.
  - `change_password` : changement du mot de passe, obligatoire à la première connexion.
  - `setup_totp` : enregistrement du TOTP.
  - `done` : l'application. L'utilisateur est alors disponible pour tous les composants (`useUser()`).
- **Connexion** : nom et mot de passe (`POST /auth/login`).
  - Si la réponse demande `totp`, l'écran passe au code à 6 chiffres (`POST /auth/totp`).
  - Cette étape est gardée par l'écran de connexion lui-même : `/auth/me` ne répond qu'à une session complète.
- **Enregistrement du TOTP** :
  - `POST /auth/totp/setup` donne un secret et son adresse `otpauth://`, affichée en QR code (bibliothèque qrcode.react, licence ISC). Le secret est aussi affiché par groupes de 4 caractères, pour une saisie à la main.
  - Le secret est demandé une seule fois et gardé, pour que le QR code ne change pas pendant qu'on le scanne.
  - Un premier code le confirme (`POST /auth/totp/confirm`).
- **Changement de mot de passe** : à la première connexion, puis depuis le menu de l'utilisateur. L'interface vérifie la longueur minimale (12, comme le contrôleur) et la confirmation avant d'envoyer.
- **Déconnexion** : `POST /auth/logout`, puis retour à l'écran de connexion. Les données lues pour l'utilisateur sont oubliées.
- **Session expirée** : toute réponse 401 d'une autre route que `/auth/login` et `/auth/totp` est interceptée par le client API. L'interface oublie alors l'utilisateur et revient à l'écran de connexion, avec le message « Your session has expired ».
- **Erreurs** : le contrôleur renvoie un code stable (`invalid_credentials`, `account_locked`…) ; l'interface le traduit (`errors.<code>` dans `en.json`). Un code inconnu donne un message générique.
- **Retour à la connexion** : le garde remplace le contenu par l'écran de connexion, puis, une fois connecté, rend l'écran de l'adresse en cours.

## Écrans du maillage (implémentés dans `src/pages/` et `src/inventory/`)

| Adresse | Écran | Avec l'accès `manage` |
| --- | --- | --- |
| `/` | Maillages : nom, accès de l'utilisateur (`manage` / `read`), date de création | création, pour l'administrateur et les utilisateurs autorisés |
| `/meshes/:id` | Un maillage et ses sites : quadrigramme, nom, AS, emplacement | renommer ou supprimer le maillage ; créer, modifier, supprimer les sites |
| `/sites/:id` | Un site et ses routeurs : numéro, nom, état (enrôlé, en attente, révoqué), dernier contact | modifier ou supprimer le site ; déclarer, renommer, supprimer les routeurs |
| `/routers/:id` | Un routeur et ses connexions : rôle, priorité, connexion directe, opérateur, adresses publiques, description | enrôlement, révocation, renommer, supprimer ; déclarer, modifier, supprimer les connexions |

- **Routeur d'adresses** : react-router (MIT), version 7. La version 8 est sortie, mais son API n'a pas encore été étudiée.
- **Droits** : seul le maillage porte le niveau d'accès de l'utilisateur (`access_level`). Ses sites, routeurs et connexions le partagent : un écran remonte au maillage (routeur → site → maillage) pour le connaître.
  - Les boutons de modification n'apparaissent qu'avec l'accès `manage`.
  - Le contrôleur vérifie de toute façon les droits.
- **Formulaires** : `@mantine/form`. Ils reprennent les règles des schémas du contrôleur avant l'envoi :
  - quadrigramme `[a-z0-9]{4}` ;
  - AS de 4200000000 à 4294967294 ; une valeur hors plage est signalée, jamais corrigée en silence ;
  - numéros `r0`–`r1` et `c0`–`c9` encore libres.
- **Modification** : un champ facultatif vidé est envoyé à `null`, ce qui l'efface (sémantique PATCH du contrôleur).
- **Enrôlement** : le bouton crée un jeton (`POST /routers/{id}/enrollment-tokens`).
  - Le jeton est affiché **une seule fois**, dans une fenêtre, avec la commande à copier : `h42-mesh-agent enroll --controller <adresse de la page> --token <jeton>`. L'adresse du contrôleur est celle de la page, car Traefik sert l'interface et l'API sur le même nom.
  - Il est oublié à la fermeture de la fenêtre. Un nouveau jeton remplace le précédent non utilisé.
  - La fenêtre rappelle l'option `--vrf` pour un routeur dont les connexions sont dans des VRF.
- **Après une modification** : toutes les données affichées sont relues.
- **À prévoir pour le conteneur `h42-mesh-gui`** : le serveur de fichiers statiques doit renvoyer `index.html` pour toute adresse inconnue (`/meshes/…`), sinon le rechargement d'une page donne une erreur 404. Le serveur de développement de Vite le fait déjà.

## Mentions obligatoires

Attribution MaxMind pour l'opérateur des connexions, par exemple en pied de page : « This product includes GeoLite2 data created by MaxMind, available from https://www.maxmind.com ».

## Points ouverts

- Rafraîchissement de l'état (intervalle de rechargement par TanStack Query, ou notifications du contrôleur).
- Disposition de la topologie dans React Flow (automatique ou positions enregistrées).
