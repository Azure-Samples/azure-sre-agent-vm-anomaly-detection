targetScope = 'subscription'

param location string = 'eastus2'
@secure()
param sshPublicKey string
param vmSize string = 'Standard_D2s_v7'
param deployVm bool = true
// customData (the VM bootstrap) is immutable: set false when re-running against an existing VM.
param createVm bool = true
param deploySreAgent bool = true
// Object id of the human who approves SRE Agent actions (gets SRE Agent Administrator); '' skips.
param sreAgentAdminObjectId string = ''
param mlStorageAccountName string = ''
param mlKeyVaultName string = ''
param mlAppInsightsName string = ''
param mlLogAnalyticsName string = ''
param mlContainerRegistryName string = ''

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-vm-anomaly-demo'
  location: location
  tags: {
    purpose: 'vm-anomaly-demo'
  }
}

resource rgMl 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-vm-anomaly-ml'
  location: location
  tags: {
    purpose: 'vm-anomaly-demo'
  }
}

module network 'modules/network.bicep' = {
  name: 'network'
  scope: rg
  params: {
    location: location
  }
}

module vm 'modules/vm.bicep' = if (deployVm && createVm) {
  name: 'vm'
  scope: rg
  params: {
    location: location
    subnetId: network.outputs.subnetId
    sshPublicKey: sshPublicKey
    vmSize: vmSize
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location: location
    deployVm: deployVm
  }
  dependsOn: [vm]
}

// Azure Activity Log -> AzureActivity table, so the SRE Agent can correlate run-command deploys.
resource activityToLaw 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'activity-to-law'
  properties: {
    workspaceId: monitoring.outputs.workspaceId
    logs: [
      { category: 'Administrative', enabled: true }
      { category: 'Security', enabled: true }
    ]
  }
}

module function 'modules/function.bicep' = {
  name: 'function'
  scope: rg
  params: {
    location: location
    workspaceCustomerId: monitoring.outputs.workspaceCustomerId
    dceEndpoint: monitoring.outputs.dceEndpoint
    dcrImmutableId: monitoring.outputs.dcrImmutableId
  }
}

module roles 'modules/roles.bicep' = {
  name: 'roles'
  scope: rg
  params: {
    location: location
    workspaceId: monitoring.outputs.workspaceId
    scoreDcrId: monitoring.outputs.scoreDcrId
    functionPrincipalId: function.outputs.principalId
  }
}

module sreAgent 'modules/sre-agent.bicep' = if (deploySreAgent) {
  name: 'sre-agent'
  scope: rg
  params: {
    location: location
    managedResourceGroupId: rg.id
    identityId: roles.outputs.agentIdentityId
    adminObjectId: sreAgentAdminObjectId
  }
}

module ml 'modules/ml.bicep' = {
  name: 'ml'
  scope: rgMl
  params: {
    location: location
    storageAccountName: mlStorageAccountName
    keyVaultName: mlKeyVaultName
    appInsightsName: mlAppInsightsName
    logAnalyticsName: mlLogAnalyticsName
    containerRegistryName: mlContainerRegistryName
  }
}

output resourceGroup string = rg.name
output workspaceCustomerId string = monitoring.outputs.workspaceCustomerId
output workspaceId string = monitoring.outputs.workspaceId
output dceEndpoint string = monitoring.outputs.dceEndpoint
output dcrImmutableId string = monitoring.outputs.dcrImmutableId
output functionName string = function.outputs.functionName
output agentIdentityId string = roles.outputs.agentIdentityId
output sreAgentName string = sreAgent.?outputs.agentName ?? ''
output mlWorkspace string = ml.outputs.workspaceName
output mlCompute string = ml.outputs.computeName
