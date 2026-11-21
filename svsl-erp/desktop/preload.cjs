const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("svsl", {
  info: () => ipcRenderer.invoke("svsl:setup-info"),
  testUrl: (url) => ipcRenderer.invoke("svsl:test-url", url),
  save: (c) => ipcRenderer.invoke("svsl:setup-save", c),
  openLogs: () => ipcRenderer.send("svsl:open-logs"),
  onStatus: (fn) => ipcRenderer.on("svsl:status", (_e, t) => fn(t)),
});
