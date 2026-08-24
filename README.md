# eBay US · CJ Ops Bot

Version **0.25.4**. Le bot fonctionne avec un périmètre volontairement unique :

- canal de vente : **eBay US** (`EBAY_US`) ;
- devise : **USD** ;
- fournisseur : **CJ Dropshipping** ;
- destination client : **États-Unis** ;
- logistique : entrepôt CJ **US prioritaire**, puis **Chine uniquement en fallback rentable**.

## Workflow

1. Le Radar mesure les annonces et vendeurs sur eBay US.
2. La recherche CJ récupère les produits et variantes correspondants.
3. Le calcul du coût livré vérifie le stock exact par entrepôt et le transport vers les États-Unis.
4. Le moteur choisit d'abord une route US admissible. Une route Chine n'est retenue que si ses seuils renforcés de marge, profit, stock et délai sont tous respectés.
5. Le Risk Engine prépare un brouillon eBay US local. Les écritures et publications restent verrouillées par défaut.

Le bot ne fabrique ni volume de recherche, ni ventes concurrentes, ni taux de conversion. Il distingue les données observées des estimations.

## Démarrage local

Prérequis : Python 3.14.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Sous Windows, activez l'environnement avec `.venv\\Scripts\\activate`.

Ouvrez ensuite `http://127.0.0.1:8765`.

## Configuration

Renseignez dans `.env` les identifiants eBay correspondant au même environnement :

- `EBAY_CLIENT_ID`
- `EBAY_CLIENT_SECRET`
- `EBAY_RUNAME`
- `EBAY_ENV=sandbox` ou `production`

Le profil `EBAY_US` / `USD` est verrouillé dans le code. Les anciennes valeurs régionales présentes dans un environnement externe ne peuvent pas modifier ce profil.

La clé CJ est administrée côté serveur et chiffrée dans le stockage persistant. L'interface ne présente plus de page de gestion des connexions. Aucune commande fournisseur n'est créée par cette version.

Avant toute écriture réelle eBay, configurez les Business Policies et les vraies clés de lieux d'expédition CJ :

- `EBAY_PAYMENT_POLICY_ID`
- `EBAY_RETURN_POLICY_ID`
- `EBAY_FULFILLMENT_POLICY_ID`
- `EBAY_CJ_US_LOCATION_KEY`
- `EBAY_CJ_CN_LOCATION_KEY`

Ne déclarez jamais un lieu US pour une variante réellement expédiée depuis la Chine.

## Verrous de sécurité

Ces valeurs restent désactivées pendant les tests :

```env
DEMO_MODE=true
EBAY_WRITE_ENABLED=false
EBAY_PUBLISH_ENABLED=false
```

Même avec un compte eBay connecté, le bot prépare uniquement des brouillons tant que les deux verrous d'écriture ne sont pas activés explicitement.

## Validation

```bash
python -m pytest -q
python -m compileall -q app tests
node --check app/static/simple_ui.js
node --check app/static/service-worker.js
```

La CI exécute les contrôles sous Python 3.14, comme l'image Docker de production.

## Santé du service

`GET /health` doit retourner notamment :

```json
{
  "ok": true,
  "version": "0.25.4",
  "operating_mode": "EBAY_US_CJ_ONLY",
  "marketplace": "EBAY_US",
  "currency": "USD",
  "destination_country": "US"
}
```

Une version n'est considérée comme déployée qu'après succès de la CI, fusion sur `main`, succès du déploiement et vérification de ce endpoint public.
