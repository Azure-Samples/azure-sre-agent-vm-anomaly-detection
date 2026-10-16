// Azure ML workspace (training + model registry for the detector) and its CPU cluster.
// Dependent resource names are parameters because a workspace cannot change them once created;
// leave them empty for a fresh environment (names derive from the resource group id).
param location string
param workspaceName string = 'mlw-vm-anomaly'
param computeName string = 'cpu-ds3v2'
param computeSize string = 'Standard_DS3_v2'
param storageAccountName string = ''
param keyVaultName string = ''
param appInsightsName string = ''
param logAnalyticsName string = ''
// Azure ML creates its ACR lazily on the first environment build; pass its name to keep it attached.
param containerRegistryName string = ''

var suffix = uniqueString(resourceGroup().id)
var storageName = empty(storageAccountName) ? 'mlwvmanost${suffix}' : storageAccountName
var kvName = empty(keyVaultName) ? 'mlwvmanokv${suffix}' : keyVaultName
var aiName = empty(appInsightsName) ? 'mlwvmanoai${suffix}' : appInsightsName
var lawName = empty(logAnalyticsName) ? 'mlwvmanolaw${suffix}' : logAnalyticsName

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource workspace 'Microsoft.MachineLearningServices/workspaces@2024-04-01' = {
  name: workspaceName
  location: location
  sku: { name: 'Basic', tier: 'Basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    friendlyName: 'VM anomaly ML'
    storageAccount: storage.id
    keyVault: keyVault.id
    applicationInsights: appInsights.id
    publicNetworkAccess: 'Enabled'
    containerRegistry: empty(containerRegistryName) ? null : resourceId('Microsoft.ContainerRegistry/registries', containerRegistryName)
  }
}

resource compute 'Microsoft.MachineLearningServices/workspaces/computes@2024-04-01' = {
  parent: workspace
  name: computeName
  location: location
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: computeSize
      vmPriority: 'Dedicated'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: 1
        nodeIdleTimeBeforeScaleDown: 'PT5M'
      }
    }
  }
}

output workspaceName string = workspace.name
output computeName string = compute.name
