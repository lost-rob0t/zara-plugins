// Zara avatar renderer preload: the only bridge between the page scene and
// the Electron host process.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("zaraAvatar", {
  ready: () => ipcRenderer.send("page-ready"),
  respond: (response) => ipcRenderer.invoke("avatar-response", response),
  emit: (event) => ipcRenderer.send("page-event", event),
  onCommand: (handler) => {
    ipcRenderer.on("avatar-command", (_event, document) => handler(document));
  },
});
