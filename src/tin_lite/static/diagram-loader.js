"use strict";

(function defineTinDiagramLoader() {
  let pending = null;

  function load() {
    if (window.TinDiagramRenderer) return Promise.resolve(window.TinDiagramRenderer);
    if (pending) return pending;
    pending = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/assets/diagram-renderer.js";
      script.onload = () => window.TinDiagramRenderer
        ? resolve(window.TinDiagramRenderer)
        : reject(new Error("Diagram renderer did not initialize."));
      script.onerror = () => reject(new Error("Diagram renderer could not be loaded."));
      document.head.append(script);
    });
    return pending;
  }

  window.TinDiagramLoader = Object.freeze({ load });
})();
