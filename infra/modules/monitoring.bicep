param location string
param deployVm bool

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' existing = {
  name: 'vm-app-01'
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-vm-anomaly-demo'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource scoreTable 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: law
  name: 'VMAnomalyScore_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    schema: {
      name: 'VMAnomalyScore_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'Computer', type: 'string' }
        { name: 'Score', type: 'real' }
        { name: 'IsAnomaly', type: 'boolean' }
        { name: 'Model', type: 'string' }
        { name: 'TopFeature', type: 'string' }
        { name: 'Details', type: 'string' }
      ]
    }
  }
}

resource guestDcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: 'dcr-vm-perf'
  location: location
  kind: 'Linux'
  properties: {
    dataSources: {
      performanceCounters: [
        {
          name: 'guest-perf'
          streams: ['Microsoft-Perf']
          samplingFrequencyInSeconds: 60
          counterSpecifiers: [
            '\\Memory\\% Used Memory'
            '\\Memory\\Available MBytes Memory'
            '\\Memory\\% Used Swap Space'
            '\\Processor(*)\\% Processor Time'
            '\\Logical Disk(*)\\% Used Space'
            '\\Network(*)\\Total Bytes'
          ]
        }
      ]
      syslog: [
        {
          name: 'guest-syslog'
          streams: ['Microsoft-Syslog']
          facilityNames: ['daemon', 'syslog', 'user']
          logLevels: ['Info', 'Notice', 'Warning', 'Error', 'Critical', 'Alert', 'Emergency']
        }
      ]
    }
    destinations: {
      logAnalytics: [
        { name: 'workspace', workspaceResourceId: law.id }
      ]
    }
    dataFlows: [
      { streams: ['Microsoft-Perf', 'Microsoft-Syslog'], destinations: ['workspace'] }
    ]
  }
}

resource association 'Microsoft.Insights/dataCollectionRuleAssociations@2023-03-11' = if (deployVm) {
  name: 'assoc-vm-perf'
  scope: vm
  properties: {
    dataCollectionRuleId: guestDcr.id
  }
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = {
  name: 'dce-vm-anomaly'
  location: location
  properties: {
    networkAcls: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource scoreDcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: 'dcr-vm-anomaly-scores'
  location: location
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      'Custom-VMAnomalyScore_CL': {
        columns: [
          { name: 'TimeGenerated', type: 'datetime' }
          { name: 'Computer', type: 'string' }
          { name: 'Score', type: 'real' }
          { name: 'IsAnomaly', type: 'boolean' }
          { name: 'Model', type: 'string' }
          { name: 'TopFeature', type: 'string' }
          { name: 'Details', type: 'string' }
        ]
      }
    }
    destinations: {
      logAnalytics: [{ name: 'workspace', workspaceResourceId: law.id }]
    }
    dataFlows: [
      {
        streams: ['Custom-VMAnomalyScore_CL']
        destinations: ['workspace']
        outputStream: 'Custom-VMAnomalyScore_CL'
      }
    ]
  }
  dependsOn: [scoreTable]
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-vm-anomaly'
  location: 'global'
  properties: {
    groupShortName: 'vmanomaly'
    enabled: true
  }
}

resource scoreAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-ml-anomaly-vm-app-01'
  location: location
  properties: {
    displayName: 'ML VM anomaly on vm-app-01'
    enabled: true
    severity: 2
    scopes: [law.id]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      allOf: [
        {
          query: 'VMAnomalyScore_CL | where Computer =~ "vm-app-01" and IsAnomaly | summarize count() by bin(TimeGenerated, 1m) | summarize AnomalyMinutes=count()'
          timeAggregation: 'Maximum'
          metricMeasureColumn: 'AnomalyMinutes'
          operator: 'GreaterThanOrEqual'
          threshold: 3
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [actionGroup.id]
    }
  }
  dependsOn: [scoreTable]
}

// Memory-specific static-threshold safety net over the same guest Perf counter AMA ships to LAW.
// The ML alert above is the detector for every anomaly class (memory, CPU, disk, ...); this
// rule only exists to show how late a naive per-metric threshold fires by comparison.
resource memAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-mem-low-vm-app-01'
  location: location
  properties: {
    displayName: 'Safety net (memory only): available memory below 200 MB on vm-app-01'
    description: 'Perf Available MBytes Memory averaged below 200 MB over five minutes'
    enabled: true
    severity: 3
    scopes: [law.id]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      allOf: [
        {
          query: 'Perf | where Computer =~ "vm-app-01" and ObjectName == "Memory" and CounterName == "Available MBytes Memory" | summarize AvailableMB=avg(CounterValue)'
          timeAggregation: 'Average'
          metricMeasureColumn: 'AvailableMB'
          operator: 'LessThan'
          threshold: 200
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [actionGroup.id]
    }
  }
}

output workspaceId string = law.id
output workspaceCustomerId string = law.properties.customerId
output dceEndpoint string = dce.properties.logsIngestion.endpoint
output dcrImmutableId string = scoreDcr.properties.immutableId
output scoreDcrId string = scoreDcr.id
