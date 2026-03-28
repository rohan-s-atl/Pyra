const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('pyraElectron', {
  getApiKey:      ()    => ipcRenderer.invoke('get-api-key'),
  setApiKey:      (key) => ipcRenderer.invoke('set-api-key', key),
  restartBackend: ()    => ipcRenderer.invoke('restart-backend'),
  isElectron:     true,
})