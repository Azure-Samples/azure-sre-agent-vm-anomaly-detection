param location string
param managedResourceGroupId string
param identityId string
param adminObjectId string = ''

var sreAgentAdministrator = 'e79298df-d852-4c6d-84f9-5d13249d1e55'

resource agent 'Microsoft.App/agents@2025-05-01-preview' = {
  name: 'sreagent-vm-anomaly'
  location: location
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    knowledgeGraphConfiguration: {
      identity: identityId
      managedResources: [managedResourceGroupId]
    }
    // Minimum monthly active flow cap; the trial waives only the always-on charge.
    monthlyAgentUnitLimit: 500
    actionConfiguration: {
      mode: 'Review'
      accessLevel: 'High'
      identity: identityId
    }
    incidentManagementConfiguration: {
      type: 'AzMonitor'
      connectionName: 'azmonitor'
    }
    mcpServers: []
  }
}

resource admin 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminObjectId)) {
  name: guid(agent.id, adminObjectId, sreAgentAdministrator)
  scope: agent
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sreAgentAdministrator)
    principalId: adminObjectId
    principalType: 'User'
  }
}

output agentName string = agent.name
