# Infrastructure

All Azure resources are defined in a single **Bicep** template at
`infra/main.bicep` and deployed with `infra/deploy.sh`.

---

## Resources created

| Resource | Type | Name pattern |
|----------|------|-------------|
| Storage Account | `Microsoft.Storage/storageAccounts` | `st{shortName}` |
| Blob containers (×3) | — | `video-input`, `doc-output`, `jobs` |
| Azure AI Speech | `Microsoft.CognitiveServices/accounts` (SpeechServices) | `speech-{baseName}` |
| Azure AI Vision | `Microsoft.CognitiveServices/accounts` (ComputerVision) | `vision-{baseName}` |
| Azure AI Foundry account | `Microsoft.CognitiveServices/accounts` (AIServices) | `aif-{baseName}` |
| Azure AI Foundry project | `accounts/projects` | `video2doc` |
| GPT-4.1 deployment | `accounts/deployments` | `gpt-4.1` |
| Container Registry | `Microsoft.ContainerRegistry/registries` | `acr{shortName}` |
| Managed Identity | `Microsoft.ManagedIdentity/userAssignedIdentities` | `id-{baseName}-api` |
| Key Vault | `Microsoft.KeyVault/vaults` | `kv-{baseName}` |
| Key Vault secrets (×4) | — | `speech-key`, `vision-key`, `openai-key`, `storage-connection-string` |
| Container Apps Environment | `Microsoft.App/managedEnvironments` | `cae-{baseName}` |
| Container App | `Microsoft.App/containerApps` | `ca-{baseName}-api` |
| Static Web App | `Microsoft.Web/staticSites` | `swa-{baseName}-ui` |

### Name construction

```bicep
var uniqueSuffix = take(uniqueString(resourceGroup().id), 6)   // e.g. a1b2c3
var baseName  = '${namePrefix}-${uniqueSuffix}'                // v2doc-a1b2c3
var shortName = replace(baseName, '-', '')                     // v2doca1b2c3
```

`uniqueString()` is deterministic for a given resource group — re-deploying
generates the same names, enabling idempotent re-runs.

---

## Template parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `environmentName` | string | `dev` | Appended to resource tags (`dev`, `staging`, `prod`) |
| `location` | string | `francecentral` | Primary region for all resources |
| `swaLocation` | string | `westeurope` | SWA region (limited availability) |
| `namePrefix` | string | `v2doc` | Short prefix ≤ 6 alphanumeric chars |
| `openAICapacity` | int | `50` | GPT-4.1 deployment capacity (tokens-per-minute × 1000) |

---

## Azure AI Foundry (AIServices)

The Foundry account uses the **2025 resource model** (`kind: AIServices`),
which replaces the legacy `kind: OpenAI` and unlocks the ai.azure.com portal.

```bicep
resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true     // enables the project hierarchy
    customSubDomainName: 'aif-${baseName}'
    disableLocalAuth: false          // allows key-based auth for the PoC
  }
}
```

A **project** (`accounts/projects`) is created as a logical namespace that
appears in the AI Foundry portal. Model deployments live on the account and
are shared across all projects in it.

The **GPT-4.1 deployment** uses `GlobalStandard` SKU, which is available in
`francecentral`. For strict EU data residency, change to `DataZoneStandard`.

```bicep
resource gpt41Deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  sku: { name: 'GlobalStandard', capacity: openAICapacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1', version: '2025-04-14' }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}
```

---

## Security: Managed Identity + Key Vault

No credentials are embedded in the container image, environment variable
plain text, or source code. The flow is:

```
1. Key Vault stores all service keys as secrets (written by Bicep at deploy time)
2. Managed Identity is granted  Key Vault Secrets User  RBAC role on the vault
3. Container App is assigned the Managed Identity
4. Container App configuration references secrets by Key Vault URL:
     name: 'speech-key'
     keyVaultUrl: 'https://kv-v2doc-a1b2c3.vault.azure.net/secrets/speech-key'
     identity: managedIdentity.id
5. At runtime, Container Apps fetches the secret value and injects it
   as the env var  AZURE_SPEECH_KEY
```

The Container Registry is pulled using the same Managed Identity with the
`AcrPull` RBAC role — no admin username/password stored anywhere.

```bicep
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'   // AcrPull
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
```

---

## Container App: scaling and resources

```bicep
resources: {
  cpu:    json('1.0')
  memory: '2Gi'
}
scale: {
  minReplicas: 0   // scale to zero when idle
  maxReplicas: 3
  rules: [
    { name: 'http-scale', http: { metadata: { concurrentRequests: '10' } } }
  ]
}
```

- **scale-to-zero** (`minReplicas: 0`) — zero compute cost when idle. Suitable
  for PoC. For production, use `minReplicas: 1` to avoid cold-start latency.
- **HTTP scaling rule** — adds a replica when concurrent HTTP requests exceed 10.
- **2 Gi memory** — headroom for ffmpeg audio/video processing and the Python
  process. 1 vCPU is sufficient for the single-threaded pipeline steps.

The initial image is the Azure placeholder (`containerapps-helloworld`).
Run `az acr build` + `az containerapp update` (see [Deployment](deployment.md))
to replace it with the real image after the first build.

---

## Blob Storage containers

| Container | Contents | Access |
|-----------|----------|--------|
| `video-input` | Original uploaded video files (not used in current pipeline) | Private |
| `doc-output` | Generated Markdown documents (not used in current pipeline) | Private |
| `jobs` | `{job_id}/state.json`, `{job_id}/{video}`, `{job_id}/result.md` | Private |

The API uses only the `jobs` container. The `video-input` and `doc-output`
containers are available for the standalone CLI (`pipeline.py --upload`).

---

## Static Web App

```bicep
resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  location: swaLocation     // westeurope
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}
```

**Free SKU** is used. The Standard SKU's "linked backend" feature was evaluated
but rejected because it installs an authentication sidecar on the Container App
that rejects unauthenticated requests. Instead, the UI calls the Container App
directly using a `window.API_BASE_URL` injected via a gitignored `config.js`.

---

## Outputs

After deployment, `deploy.sh` prints these values which are needed for
subsequent steps:

| Output | Used for |
|--------|---------|
| `apiUrl` | Setting `window.API_BASE_URL` in `config.js` |
| `uiUrl` | Opening the deployed UI |
| `acrLoginServer` | Building and pushing the Docker image |
| `containerAppName` | Updating the Container App image |
| `keyVaultName` | Manual secret inspection if needed |
| `storageAccountName` | Manual blob inspection if needed |
| `aiFoundryEndpoint` | Set as `AZURE_OPENAI_ENDPOINT` in the Container App |

---

## Dependency graph

```
storageAccount
  └── blobService
        ├── containerVideoInput
        ├── containerDocOutput
        └── containerJobs

speechService
visionService

aiFoundry
  ├── aiFoundryProject
  └── gpt41Deployment

containerRegistry

managedIdentity
  ├── acrPullRole        (scope: containerRegistry)
  └── kvSecretsUserRole  (scope: keyVault)

keyVault
  ├── secretSpeechKey    (value: speechService.listKeys().key1)
  ├── secretVisionKey    (value: visionService.listKeys().key1)
  ├── secretOpenAIKey    (value: aiFoundry.listKeys().key1)
  └── secretStorageConn  (value: storageAccount connection string)

containerAppsEnv
  └── containerApp       (depends on: acrPullRole, kvSecretsUserRole, all secrets)

staticWebApp
```
