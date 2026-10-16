param location string
param subnetId string
@secure()
param sshPublicKey string
param adminUsername string = 'azureuser'
param vmSize string = 'Standard_B2s'
@description('Git ref of app/ baked into the image at first boot (recorded in DEPLOY_LOG).')
param appRef string = 'bootstrap'

resource publicIp 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: 'pip-vm-app-01'
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: 'nic-vm-app-01'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'primary'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: { id: subnetId }
          publicIPAddress: { id: publicIp.id }
        }
      }
    ]
  }
}

var bootstrap = format('''#!/bin/bash
set -euo pipefail
mkdir -p /var/tmp/demo-app-install
printf '%s' '{0}' | base64 -d > /var/tmp/demo-app-install/server.py
printf '%s' '{1}' | base64 -d > /var/tmp/demo-app-install/demo-app.service
printf '%s' '{2}' | base64 -d > /var/tmp/demo-app-install/deploy.sh
printf '%s' '{3}' | base64 -d > /var/tmp/demo-app-install/install.sh
chmod +x /var/tmp/demo-app-install/*.sh
DEMO_APP_REF='{4}' /var/tmp/demo-app-install/install.sh
''', base64(loadTextContent('../../app/server.py')), base64(loadTextContent('../../app/demo-app.service')), base64(loadTextContent('../../app/deploy.sh')), base64(loadTextContent('../../app/install.sh')), appRef)

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: 'vm-app-01'
  location: location
  tags: {
    app: 'demo-app'
  }
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: { storageAccountType: 'Standard_LRS' }
      }
    }
    osProfile: {
      computerName: 'vm-app-01'
      adminUsername: adminUsername
      customData: base64(bootstrap)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [{ id: nic.id }]
    }
    diagnosticsProfile: {
      bootDiagnostics: { enabled: true }
    }
  }
}

resource ama 'Microsoft.Compute/virtualMachines/extensions@2024-03-01' = {
  parent: vm
  name: 'AzureMonitorLinuxAgent'
  location: location
  properties: {
    publisher: 'Microsoft.Azure.Monitor'
    type: 'AzureMonitorLinuxAgent'
    typeHandlerVersion: '1.0'
    autoUpgradeMinorVersion: true
    enableAutomaticUpgrade: true
  }
}

output vmId string = vm.id
