param location string
param workspaceId string
param scoreDcrId string
param functionPrincipalId string

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: 'law-vm-anomaly-demo'
}

resource scoreDcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' existing = {
  name: 'dcr-vm-anomaly-scores'
}

var lawReader = '73c42c96-874c-492b-b04d-ab87d138a893'
var metricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'
var agentRoles = [
  'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Reader
  lawReader
  '43d0d8ad-25c7-4714-9337-8ba259a9fe05' // Monitoring Reader
  '749f88d5-cbae-40b8-bcfc-e573ddc772fa' // Monitoring Contributor
  '9980e02c-c2be-4d73-94e8-173b1dc7cf3c' // Virtual Machine Contributor
]

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-sreagent-vm-anomaly'
  location: location
}

resource functionLawRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workspaceId, functionPrincipalId, lawReader)
  scope: law
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', lawReader)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource functionDcrRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(scoreDcrId, functionPrincipalId, metricsPublisher)
  scope: scoreDcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', metricsPublisher)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource agentRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in agentRoles: {
  name: guid(resourceGroup().id, identity.id, role)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

output agentIdentityId string = identity.id
