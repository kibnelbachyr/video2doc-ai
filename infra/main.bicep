/*
  main.bicep
  ----------
  Provisions ALL Azure resources for video2doc-ai in a single template.

  Resources created
  ─────────────────
  • Storage Account  (containers: video-input, doc-output, jobs)
  • Azure AI Speech
  • Azure AI Vision  (Image Analysis 4.0)
  • Azure AI Foundry (AIServices account + project + gpt-4.1 deployment)
  • Azure Container Registry
  • User-Assigned Managed Identity
  • Key Vault        (stores all service keys)
  • Container Apps Environment + Container App  (API backend)
  • Azure Static Web Apps                       (UI frontend)
*/

// ── Parameters ────────────────────────────────────────────────────────────────

@description('Short environment label appended to resource names.')
@allowed(['dev', 'staging', 'prod'])
param environmentName string = 'dev'

@description('Primary Azure region for all resources. France Central recommended for EU data residency.')
param location string = 'francecentral'

@description('Region for Azure Static Web Apps (limited availability; westeurope is closest to France Central).')
@allowed(['eastus2', 'westus2', 'centralus', 'eastasia', 'westeurope', 'eastus'])
param swaLocation string = 'westeurope'

@description('Short prefix for resource names (max 6 alphanumeric chars).')
@maxLength(6)
param namePrefix string = 'v2doc'

@description('GPT-4.1 deployment capacity in tokens-per-minute thousands.')
param openAICapacity int = 50

// ── Name construction ─────────────────────────────────────────────────────────

var uniqueSuffix = take(uniqueString(resourceGroup().id), 6)
var baseName = '${namePrefix}-${uniqueSuffix}'   // e.g. v2doc-a1b2c3
var shortName = replace(baseName, '-', '')         // e.g. v2doca1b2c3

var tags = {
  application: 'video2doc-ai'
  environment: environmentName
}

// ── Storage Account ───────────────────────────────────────────────────────────

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'st${shortName}'   // max 24 chars; 'st' + shortName ≤ 2+15 = 17 ✓
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource containerVideoInput 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'video-input'
  properties: { publicAccess: 'None' }
}

resource containerDocOutput 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'doc-output'
  properties: { publicAccess: 'None' }
}

resource containerJobs 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'jobs'
  properties: { publicAccess: 'None' }
}

// ── Azure AI Speech ───────────────────────────────────────────────────────────

resource speechService 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'speech-${baseName}'
  location: location
  tags: tags
  kind: 'SpeechServices'
  sku: { name: 'S0' }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: 'speech-${baseName}'
  }
}

// ── Azure AI Vision ───────────────────────────────────────────────────────────

resource visionService 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'vision-${baseName}'
  location: location
  tags: tags
  kind: 'ComputerVision'
  sku: { name: 'S1' }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: 'vision-${baseName}'
  }
}

// ── Azure AI Foundry ──────────────────────────────────────────────────────────
// Uses the new AIServices resource type (kind: AIServices) introduced in 2025,
// replacing the standalone Azure OpenAI Service (kind: OpenAI).
//
// allowProjectManagement: true enables the ai.azure.com portal experience and
// the project hierarchy. The project is a logical namespace for experiments;
// model deployments live on the account and are shared across projects.
//
// Model: gpt-4.1 GlobalStandard — available in francecentral.
// For strict EU data residency, change SKU name to 'DataZoneStandard'.
//
// Reference: https://learn.microsoft.com/azure/ai-foundry/

resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: 'aif-${baseName}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    customSubDomainName: 'aif-${baseName}'
    disableLocalAuth: false
  }
}

resource aiFoundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: aiFoundry
  name: 'video2doc'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'video2doc-ai'
    description: 'Video-to-documentation pipeline project'
  }
}

resource gpt41Deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: aiFoundry
  name: 'gpt-4.1'
  sku: {
    name: 'GlobalStandard'
    capacity: openAICapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1'
      version: '2025-04-14'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// ── Azure Container Registry ──────────────────────────────────────────────────

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${shortName}'  // max 50 chars; 'acr' + shortName ≤ 3+15 = 18 ✓
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false  // auth via Managed Identity, not admin password
  }
}

// ── User-Assigned Managed Identity ───────────────────────────────────────────

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${baseName}-api'
  location: location
  tags: tags
}

// AcrPull role → allows Container App to pull images without a password
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, managedIdentity.id, 'acrpull')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'  // AcrPull
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Key Vault ─────────────────────────────────────────────────────────────────

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${baseName}'  // max 24 chars; 'kv-' + baseName ≤ 3+13 = 16 ✓
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

// Key Vault Secrets User → allows Container App to read secrets
resource kvSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentity.id, 'kvsecrets')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'  // Key Vault Secrets User
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Store all service credentials as Key Vault secrets
resource secretSpeechKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'speech-key'
  properties: { value: speechService.listKeys().key1 }
}

resource secretVisionKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'vision-key'
  properties: { value: visionService.listKeys().key1 }
}

resource secretOpenAIKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'openai-key'
  properties: { value: aiFoundry.listKeys().key1 }
}

resource secretStorageConn 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'storage-connection-string'
  properties: {
    value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
  }
}

// ── Container Apps Environment ────────────────────────────────────────────────

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'cae-${baseName}'
  location: location
  tags: tags
  properties: {}
}

// ── Container App  (API backend) ──────────────────────────────────────────────
// On first deploy the ACR is empty → uses a placeholder image.
// CI/CD (deploy-app.yml) updates the image after the first successful build.

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'ca-${baseName}-api'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        corsPolicy: {
          allowedOrigins: ['*']
          allowedMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']
          allowedHeaders: ['*']
          maxAge: 300
        }
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: managedIdentity.id
        }
      ]
      secrets: [
        {
          name: 'speech-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/speech-key'
          identity: managedIdentity.id
        }
        {
          name: 'vision-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/vision-key'
          identity: managedIdentity.id
        }
        {
          name: 'openai-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/openai-key'
          identity: managedIdentity.id
        }
        {
          name: 'storage-conn'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/storage-connection-string'
          identity: managedIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            { name: 'AZURE_SPEECH_KEY',                      secretRef: 'speech-key'   }
            { name: 'AZURE_SPEECH_REGION',                   value: location            }
            { name: 'AZURE_VISION_ENDPOINT',                 value: visionService.properties.endpoint }
            { name: 'AZURE_VISION_KEY',                      secretRef: 'vision-key'   }
            { name: 'AZURE_OPENAI_ENDPOINT',                 value: aiFoundry.properties.endpoint }
            { name: 'AZURE_OPENAI_KEY',                      secretRef: 'openai-key'   }
            { name: 'AZURE_OPENAI_DEPLOYMENT',               value: 'gpt-4.1'          }
            { name: 'AZURE_OPENAI_API_VERSION',              value: '2025-04-01-preview' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING',       secretRef: 'storage-conn' }
            { name: 'FRAMES_PER_MINUTE',                     value: '2'                }
            { name: 'MOCK_TRANSCRIPTION',                    value: 'false'            }
            { name: 'MOCK_VISION',                           value: 'false'            }
          ]
        }
      ]
      scale: {
        minReplicas: 0   // scale-to-zero when idle → no idle cost
        maxReplicas: 3
        rules: [
          {
            name: 'http-scale'
            http: { metadata: { concurrentRequests: '10' } }
          }
        ]
      }
    }
  }
  dependsOn: [
    acrPullRole
    kvSecretsUserRole
    secretSpeechKey
    secretVisionKey
    secretOpenAIKey
    secretStorageConn
  ]
}

// ── Azure Static Web Apps  (UI frontend) ─────────────────────────────────────

resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: 'swa-${baseName}-ui'
  location: swaLocation
  tags: tags
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

// ── Outputs ───────────────────────────────────────────────────────────────────

output resourceGroupName string = resourceGroup().name
output apiUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output uiUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output acrLoginServer string = containerRegistry.properties.loginServer
output containerAppName string = containerApp.name
output keyVaultName string = keyVault.name
output storageAccountName string = storageAccount.name
output aiFoundryEndpoint string = aiFoundry.properties.endpoint
output aiFoundryProjectName string = aiFoundryProject.name
