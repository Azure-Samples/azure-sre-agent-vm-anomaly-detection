using './main.bicep'

param location = 'eastus2'
param sshPublicKey = readEnvironmentVariable('VM_ANOMALY_SSH_PUBLIC_KEY')
param vmSize = readEnvironmentVariable('VM_ANOMALY_VM_SIZE', 'Standard_D2s_v7')
param deployVm = readEnvironmentVariable('VM_ANOMALY_DEPLOY_VM', 'true') == 'true'
param createVm = readEnvironmentVariable('VM_ANOMALY_CREATE_VM', 'true') == 'true'
param deploySreAgent = readEnvironmentVariable('VM_ANOMALY_DEPLOY_SRE_AGENT', 'true') == 'true'
param sreAgentAdminObjectId = readEnvironmentVariable('VM_ANOMALY_SRE_ADMIN_OBJECT_ID', '')
param mlStorageAccountName = readEnvironmentVariable('VM_ANOMALY_ML_STORAGE', '')
param mlKeyVaultName = readEnvironmentVariable('VM_ANOMALY_ML_KEYVAULT', '')
param mlAppInsightsName = readEnvironmentVariable('VM_ANOMALY_ML_APPINSIGHTS', '')
param mlLogAnalyticsName = readEnvironmentVariable('VM_ANOMALY_ML_LAW', '')
param mlContainerRegistryName = readEnvironmentVariable('VM_ANOMALY_ML_ACR', '')
