#!/usr/bin/env bash
# deploy.sh  –  One-shot deployment of all Azure resources
#
# Usage:
#   ./infra/deploy.sh
#
# Environment variables (all optional – defaults shown below):
#   RESOURCE_GROUP   Name of the resource group    (default: rg-video2doc-ai)
#   LOCATION         Primary Azure region           (default: eastus)
#   ENVIRONMENT      Environment label              (default: dev)
#   NAME_PREFIX      Short resource prefix ≤6 chars (default: v2doc)
#
# Prerequisites:
#   - Azure CLI  ≥ 2.50 installed and logged in  (az login)
#   - Bicep CLI  (installed automatically by az deployment group create)
#   - jq         (for output parsing)

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-video2doc-ai}"
LOCATION="${LOCATION:-francecentral}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
NAME_PREFIX="${NAME_PREFIX:-v2doc}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================================"
echo "  video2doc-ai  –  Azure Deployment"
echo "========================================================"
echo "  Resource Group : $RESOURCE_GROUP"
echo "  Location       : $LOCATION"
echo "  Environment    : $ENVIRONMENT"
echo "  Name Prefix    : $NAME_PREFIX"
echo "========================================================"
echo ""

# ── 1. Create resource group ──────────────────────────────────────────────────
echo "[1/3] Creating resource group '$RESOURCE_GROUP' ..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --tags application=video2doc-ai environment="$ENVIRONMENT" \
  --output table

# ── 2. Deploy Bicep template ──────────────────────────────────────────────────
echo ""
echo "[2/3] Deploying Bicep template (this takes ~5 minutes) ..."
OUTPUTS=$(az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$SCRIPT_DIR/main.bicep" \
  --parameters \
      environmentName="$ENVIRONMENT" \
      location="$LOCATION" \
      namePrefix="$NAME_PREFIX" \
  --query "properties.outputs" \
  --output json)

# ── 3. Display results ────────────────────────────────────────────────────────
echo ""
echo "[3/3] Deployment complete!"
echo ""

API_URL=$(echo "$OUTPUTS"         | jq -r '.apiUrl.value')
UI_URL=$(echo "$OUTPUTS"          | jq -r '.uiUrl.value')
ACR_SERVER=$(echo "$OUTPUTS"      | jq -r '.acrLoginServer.value')
CONTAINER_APP=$(echo "$OUTPUTS"   | jq -r '.containerAppName.value')
KV_NAME=$(echo "$OUTPUTS"         | jq -r '.keyVaultName.value')
STORAGE=$(echo "$OUTPUTS"         | jq -r '.storageAccountName.value')
FOUNDRY_ENDPOINT=$(echo "$OUTPUTS" | jq -r '.aiFoundryEndpoint.value')

echo "  API URL        : $API_URL"
echo "  UI URL         : $UI_URL"
echo "  ACR            : $ACR_SERVER"
echo "  Container App  : $CONTAINER_APP"
echo "  Key Vault      : $KV_NAME"
echo "  Storage        : $STORAGE"
echo "  AI Foundry     : $FOUNDRY_ENDPOINT"
echo ""
echo "========================================================"
echo "  Next steps"
echo "========================================================"
echo ""
echo "  1. Build & push the API image to ACR:"
echo "     az acr build --registry $ACR_SERVER \\"
echo "       --image video2doc-api:latest \\"
echo "       --file Dockerfile ."
echo ""
echo "  2. Update the Container App to use the real image:"
echo "     az containerapp update \\"
echo "       --name $CONTAINER_APP \\"
echo "       --resource-group $RESOURCE_GROUP \\"
echo "       --image $ACR_SERVER/video2doc-api:latest"
echo ""
echo "  3. Get the SWA deployment token and deploy the UI:"
echo "     SWA_TOKEN=\$(az staticwebapp secrets list \\"
echo "       --name swa-* -g $RESOURCE_GROUP \\"
echo "       --query 'properties.apiKey' -o tsv)"
echo "     sed -i \"s|__API_URL__|$API_URL|g\" ui/index.html"
echo "     npx @azure/static-web-apps-cli deploy ui \\"
echo "       --deployment-token \$SWA_TOKEN"
echo ""
