# video2doc-ai

> **Génère une documentation produit structurée et multilingue à partir de vidéos internes grâce à l'IA Azure.**

Fournissez un enregistrement vidéo d'une démonstration produit, d'une session de
formation ou d'une démonstration technique. L'application transcrit l'audio, analyse
les visuels affichés à l'écran, et produit une documentation Markdown prête à publier
au format **Diátaxis** — automatiquement dans la même langue que la vidéo (français
ou anglais).

---

## Fonctionnement

```
┌─────────────┐     POST /api/jobs      ┌──────────────────────────────────────────┐
│  Interface  │ ───────────────────────▶│          FastAPI  (Container App)        │
│  navigateur │ ◀─── job_id + polling ──│                                          │
│  (SWA)      │                         │  1. Envoi vidéo    → Azure Blob Storage  │
└─────────────┘                         │  2. Transcription  → Azure AI Speech     │
                                        │  3. Extraction images → ffmpeg          │
                                        │  4. Analyse images  → Azure AI Vision   │
                                        │  5. Génération doc → Azure AI Foundry   │
                                        │                       GPT-4.1            │
                                        └──────────────────────────────────────────┘
```

Le navigateur envoie un fichier vidéo. L'API démarre un thread en arrière-plan qui
exécute le pipeline en cinq étapes, en mettant à jour un document d'état du job dans
Blob Storage après chaque étape. Le navigateur interroge le serveur toutes les 2
secondes et affiche la progression en direct ; une fois le job terminé, il affiche
le Markdown généré et propose son téléchargement.

---

## Composants

| Composant | Description |
|---|---|
| **API backend** (`api/`) | Service FastAPI exposant les endpoints de création/statut/résultat des jobs, exécute le pipeline dans un thread en arrière-plan |
| **Pipeline de traitement** (`src/`) | Transcription, extraction d'images, analyse d'images et génération de documentation — partagé entre l'API et le CLI |
| **Interface utilisateur** (`ui/`) | Application monopage (HTML/CSS/JS natif, sans étape de build) pour l'envoi de fichiers, le suivi de progression et l'aperçu du résultat |
| **CLI** (`pipeline.py`) | Point d'entrée en ligne de commande autonome pour exécuter le même pipeline sans API ni navigateur |
| **Infrastructure as Code** (`infra/`) | Template Azure Bicep provisionnant l'environnement complet en un seul déploiement |

---

## Architecture

```
                    ┌──────────────────────────┐
                    │  Azure Static Web Apps   │
                    │  (Vanilla JS SPA)        │
                    └────────────┬─────────────┘
                                 │ POST /api/jobs
                                 │ GET  /api/jobs/{id}
                                 │ GET  /api/jobs/{id}/result
                                 ▼
                    ┌──────────────────────────┐
                    │  Azure Container Apps    │◄── Managed Identity
                    │  FastAPI  (api/)         │
                    └────────────┬─────────────┘         │
                                 │                   ┌────┴──────────────────────┐
                    pipeline (séquentiel)             ▼                           ▼
                                 │          ┌──────────────────┐  ┌──────────────────────┐
                                 ▼          │  Azure Container │  │  Azure Key Vault     │
          ┌──────────────────────────┐      │  Registry        │  │  (secrets)           │
          │  ① Azure AI Speech      │      │  (AcrPull)       │  │  (KV Secrets User)   │
          │     (transcription)     │      └──────────────────┘  └──────────────────────┘
          └──────────────┬───────────┘
                         │
                         ▼
          ┌──────────────────────────┐
          │  ② ffmpeg                │
          │     (extraction images) │
          └──────────────┬───────────┘
                         │
                         ▼
          ┌──────────────────────────┐
          │  ③ Azure AI Vision      │
          │     (légende + OCR)     │
          └──────────────┬───────────┘
                         │
                         ▼
          ┌──────────────────────────┐       ┌──────────────────────────┐
          │  ④ Azure AI Foundry     │       │  Azure Blob Storage      │
          │     GPT-4.1             │──────▶│  jobs/{id}/state.json    │
          └──────────────────────────┘       │  jobs/{id}/{video_file}  │
                                             │  jobs/{id}/result.md     │
                                             └──────────────────────────┘
```

> `state.json` est mis à jour par le Container App après chaque étape du pipeline, pas seulement à la fin.
> ffmpeg s'exécute comme un sous-processus local dans le conteneur — ce n'est pas un service Azure externe.

### Services Azure

| Service | SKU | Rôle |
|---------|-----|------|
| Azure Static Web Apps | Free | Héberge l'interface JS native dans le navigateur |
| Azure Container Apps | Consumption | Exécute le backend FastAPI + le pipeline |
| Azure Container Registry | Basic | Stocke l'image Docker |
| Azure AI Speech | S0 | Convertit l'audio de la vidéo en texte |
| Azure AI Vision 4.0 | S1 | Légendes et OCR sur les images extraites |
| Azure AI Foundry (GPT-4.1) | S0 GlobalStandard | Génère la documentation au format Diátaxis |
| Azure Blob Storage | Standard LRS | Persiste l'état des jobs et le Markdown généré |
| Azure Key Vault | Standard | Stocke tous les secrets des services |

**Région cible :** `francecentral` pour toutes les ressources · SWA en `westeurope`.

Aucun identifiant n'est jamais stocké dans l'image du conteneur ni en clair dans
les variables d'environnement. Une identité managée assignée par l'utilisateur lit
tous les secrets depuis Key Vault au démarrage et récupère l'image Docker depuis
le Container Registry — sans aucun mot de passe.

---

## Étapes de déploiement

Prérequis : Azure CLI ≥ 2.50, connecté (`az login`) avec un abonnement sélectionné.

```bash
# 1. Provisionner toutes les ressources Azure (~5 minutes)
./infra/deploy.sh
# Notez l'URL de l'API, le nom du Container App, le serveur de connexion ACR et le nom du SWA affichés.

# 2. Construire l'image de l'API dans le cloud et la pousser vers ACR
az acr build \
  --registry <acr-login-server> \
  --image video2doc-api:latest \
  --file Dockerfile .

# 3. Faire pointer le Container App vers la nouvelle image
az containerapp update \
  --name <container-app-name> \
  --resource-group rg-video2doc-ai \
  --image <acr-login-server>/video2doc-api:latest

# 4. Déployer l'interface sur Static Web Apps
echo "window.API_BASE_URL = 'https://<api-url>';" > ui/config.js
SWA_TOKEN=$(az staticwebapp secrets list --name <swa-name> \
  --resource-group rg-video2doc-ai --query 'properties.apiKey' -o tsv)
npx @azure/static-web-apps-cli deploy ui --deployment-token "$SWA_TOKEN"

# 5. Vérifier
curl https://<api-url>/health   # attendu : {"status":"ok"}
```

Voir [docs/deployment.md](docs/deployment.md) pour le guide complet, incluant le
redéploiement après modification du code et le dépannage.

---

## Documentation complémentaire

| Page | Contenu |
|------|---------|
| [Architecture](docs/architecture.md) | Conception des composants, flux de données, choix technologiques |
| [Pipeline](docs/pipeline.md) | Détail des 5 étapes de traitement |
| [API REST](docs/api.md) | Tous les endpoints, schémas de requête/réponse, codes d'erreur |
| [Frontend](docs/frontend.md) | Composants UI, logique JavaScript, mécanisme de polling |
| [Infrastructure](docs/infrastructure.md) | Template Bicep, ressources Azure, identité managée |
| [Développement local](docs/local-dev.md) | Installation, mode mock, utilisation du CLI, Docker |
| [Déploiement](docs/deployment.md) | Guide complet de déploiement Azure |
| [Configuration](docs/configuration.md) | Référence de toutes les variables d'environnement |
