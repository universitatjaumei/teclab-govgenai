// Abrir el panel lateral al pulsar el icono de la extensión. Es todo lo que hace el fondo.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
