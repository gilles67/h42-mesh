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

## Mentions obligatoires

Attribution MaxMind pour l'opérateur des connexions, par exemple en pied de page : « This product includes GeoLite2 data created by MaxMind, available from https://www.maxmind.com ».

## Points ouverts

- Rafraîchissement de l'état (intervalle de rechargement par TanStack Query, ou notifications du contrôleur).
- Disposition de la topologie dans React Flow (automatique ou positions enregistrées).
