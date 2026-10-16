param location string
param workspaceCustomerId string
param dceEndpoint string
param dcrImmutableId string

var suffix = uniqueString(resourceGroup().id)
var functionName = 'func-vm-anomaly-${suffix}'
var containerName = 'app-package'
var blobContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var queueContributor = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var tableContributor = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stvm${suffix}'
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
  resource blob 'blobServices' = {
    name: 'default'
    resource container 'containers' = {
      name: containerName
      properties: { publicAccess: 'None' }
    }
  }
}

resource storageIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-func-storage-vm-anomaly'
  location: location
}

resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, storageIdentity.id, blobContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributor)
    principalId: storageIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource queueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, storageIdentity.id, queueContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueContributor)
    principalId: storageIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource tableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, storageIdentity.id, tableContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', tableContributor)
    principalId: storageIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-vm-anomaly-${suffix}'
  location: location
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource app 'Microsoft.Web/sites@2024-04-01' = {
  name: functionName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${storageIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${containerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: storageIdentity.id
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
    }
  }
  dependsOn: [blobRole, queueRole, tableRole, storage::blob::container]
}

resource settings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: app
  name: 'appsettings'
  properties: {
    AzureWebJobsStorage__accountName: storage.name
    AzureWebJobsStorage__credential: 'managedidentity'
    AzureWebJobsStorage__clientId: storageIdentity.properties.clientId
    LAW_WORKSPACE_ID: workspaceCustomerId
    DCE_ENDPOINT: dceEndpoint
    DCR_IMMUTABLE_ID: dcrImmutableId
    DCR_STREAM: 'Custom-VMAnomalyScore_CL'
    TARGET_COMPUTER: 'vm-app-01'
    SCORE_THRESHOLD: '0.8'
  }
}

output principalId string = app.identity.principalId
output functionName string = app.name
