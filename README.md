# eBay Ops Bot v0.14.3

Application cloud et locale pensée pour être utilisée sans connaissances en programmation. La v0.14.3 garde le parcours **détecter une piste → trouver un fournisseur → calculer le coût réel → créer un produit → vendre → suivre le SAV**, avec les mêmes données sur Windows, Mac et iPhone après hébergement.

## Nouveautés v0.14.3

- remplacement des tendances YouTube généralistes par des Shorts e-commerce récents ;
- veille ciblée sur `#ecommerce`, `#dropshipping`, `#amazonfinds`, `#tiktokmademebuyit` et `#productfinds` ;
- exclusion des vidéos de plus de trois minutes et des résultats sans contexte commercial ;
- filtrage des mots génériques afin de faire ressortir des types de produits plutôt que « viral » ou « dropshipping » ;
- affichage des Shorts retenus avec vues, durée et hashtags ;
- anciens thèmes généralistes exclus de la boîte d'opportunités et des recherches fabricants.

## Nouveautés v0.14.2

- connecteur Amazon SP-API strictement limité au Radar et à la lecture seule ;
- relevés Amazon France, Allemagne, Italie, Espagne, Royaume-Uni et États-Unis ;
- catalogue, catégories, rangs de vente et historique des résultats disponibles ;
- prix et nombre d'offres ajoutés lorsque le rôle Amazon Pricing est autorisé ;
- surveillance Amazon France automatique toutes les six heures pour les produits suivis ;
- Amazon fonctionne dans le Radar indépendamment de la connexion eBay Production.

## Nouveautés v0.14.1

- bouton d’export d’un diagnostic texte sécurisé, sans secret ni donnée client ;
- onglet Aide complet pour présenter le bot à un associé ;
- parcours guidé des connexions jusqu’au SAV ;
- explication claire de chaque onglet, des scores et des limites des automatismes ;
- rappel des actions qui exigent toujours une validation humaine.

## Nouveautés v0.14.0

- mode cloud privé avec connexion par e-mail et mot de passe ;
- application web installable (PWA) sur Windows, macOS et l'écran d'accueil iPhone ;
- mises à jour centralisées : le redéploiement remplace l'ancienne version sur tous les appareils ;
- base SQLite placée sur un disque persistant et sauvegardée quotidiennement ;
- création et téléchargement manuel des sauvegardes dans Paramètres ;
- image Docker portable et Blueprint Render prêts à déployer ;
- protections réseau : hôtes autorisés, origine contrôlée, cookie signé sécurisé et limitation des tentatives de connexion ;
- mode local Windows/Mac conservé, ainsi que `LANCER_BOT.bat` et `DIAGNOSTIC_WINDOWS.bat`.

## Fonctions v0.13.0 conservées

- Annuaire de 19 plateformes de sourcing et fournisseurs de niche, filtrable par niche et par accès CSV/XML/API/datafeed.
- Score produit local sur 100 recalculé automatiquement après chaque changement, y compris pour les imports CJ.
- Score de préparation séparé du score de demande eBay pour ne jamais inventer un signal marché.
- Correction de la sauvegarde du Risk Engine : les nouvelles règles sont appliquées immédiatement.
- Onglet SAV avec priorités, échéances, statuts et brouillons de réponse locaux supprimables.
- Feuille de route multicanale : Cdiscount/Octopia, Kaufland, Amazon, TikTok Shop et Etsy.

## Fonctions v0.12.0 conservées

- détection automatique de thèmes sans mot-clé à partir des vidéos YouTube populaires d'un pays ;
- extraction explicable des mots récurrents, avec nombre d'apparitions et échantillon public ;
- centre Fournisseurs unique regroupant CJ, DropXL, Printful, Printify, Gelato, HyperSKU, Banggood, Wholesale2B, Alibaba, partenaires manuels et fabricants ;
- recherche universelle dans les catalogues API réellement connectés ;
- recherche fabricant assistée depuis une niche du Radar ;
- carnet de contacts fabricants, préparation RFQ et suppression des brouillons ;
- boîte d'opportunités dans Produits pour les niches détectées et produits CJ sélectionnés ;
- conversion d'un produit CJ analysé en produit local, toujours en Dry-run ;
- vrai lien de téléchargement du modèle CSV ;
- bulles d'aide `?` sur les notions pouvant prêter à confusion ;
- une source chiffrée avec une ancienne clé n'empêche plus les autres connexions de charger ;
- migration Windows d'une paire cohérente `.env` + base locale pour éviter de casser les clés enregistrées.

## Ce que signifie « automatique »

YouTube autorise la lecture de son classement public `mostPopular` par pays. Le bot l'utilise toutes les six heures quand YouTube est connecté, puis compte les thèmes présents dans les titres et tags publics.

Ce signal ne représente **ni un volume de recherche, ni des ventes, ni un taux de conversion**. Une niche reste une piste jusqu'à confirmation par eBay Production, un fournisseur, le coût livré et la conformité.

TikTok Commercial Content et Etsy restent des sources de confirmation ciblée : elles sont interrogées avec un thème précis détecté automatiquement ou saisi par l'utilisateur.

## Fournisseurs et fabricants

Le centre Fournisseurs distingue clairement :

- les catalogues connectés et utilisables dans les recherches Produits ;
- les accès API encore à demander, comme Wholesale2B ou HyperSKU ;
- les partenaires manuels alimentés par CSV ;
- les contacts fabricants et usines ;
- les RFQ conservés en brouillon local.

Le bot peut récupérer automatiquement un catalogue uniquement lorsqu'une API officielle ou un flux public autorisé est disponible. Il n'invente jamais un email, un contact ou un fichier CSV. Les fiches trouvées sur un annuaire doivent être vérifiées avant enregistrement, échantillon ou négociation.

## Produits

- produits manuels, catalogues CSV et produits issus des fournisseurs connectés ;
- niches du Radar visibles dans une boîte d'opportunités ;
- filtres par fournisseur, statut, score et marge ;
- statuts `À tester`, `Winner` et `Rejeté` ;
- coût fournisseur + transport + frais eBay + publicité + réserve retours + frais fixes ;
- prix plancher et prix conseillé ;
- Opportunity Score uniquement à partir des données réellement disponibles ;
- préparation eBay sous forme de brouillon local.

## Assistant intelligent

La v0.14.0 utilise des règles explicables pour extraire les thèmes, calculer les marges, classer les risques, préparer les RFQ et proposer des brouillons SAV. Aucun service d'IA payant n'est activé silencieusement. Une IA générative pourra être branchée plus tard pour proposer plusieurs titres, descriptions ou messages, mais elle restera derrière les contrôles conformité, rentabilité, doublon et validation humaine.

## Sécurité par défaut

```text
EBAY_ENV=sandbox
DEMO_MODE=true
EBAY_WRITE_ENABLED=false
EBAY_PUBLISH_ENABLED=false
```

Aucun paiement, aucune commande fournisseur et aucune publication eBay réelle ne sont déclenchés. AliExpress reste une source de comparaison uniquement. Pinterest et Reddit ne sont pas utilisés.

## Démarrage Windows

1. Décompresse complètement le ZIP.
2. Ouvre le dossier `ebay-bot-v0.14.0`.
3. Double-clique sur **`LANCER_BOT.bat`**.
4. La première utilisation installe les dépendances et cherche la dernière installation locale complète.
5. Le navigateur s'ouvre lorsque le bot répond réellement.
6. Garde la fenêtre noire ouverte pendant l'utilisation.

Adresse locale : `http://127.0.0.1:8765`

## Import CSV

Le bouton **Télécharger le vrai modèle** télécharge `modele_fournisseur_ebay.csv`. Le bot accepte les séparateurs virgule, point-virgule et tabulation. Chaque ligne doit contenir au minimum :

- `supplier_sku` ;
- `title` ;
- `supplier_cost`.

## Diagnostic

En cas de problème, double-clique sur `DIAGNOSTIC_WINDOWS.bat`. Le rapport `diagnostic.txt` ne contient aucune clé API. `REPAIR_WINDOWS.bat` répare uniquement l'environnement Python et conserve la configuration et la base locale.
