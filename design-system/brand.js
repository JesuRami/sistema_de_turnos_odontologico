/**
 * Punto único de cambio del nombre de marca en previews HTML.
 * No contiene lógica de producto: solo reemplaza el texto de [data-brand-name].
 * Mantener el script autocontenido y sin dependencias para que un archivo local funcione.
 */
(function () {
  "use strict";

  var BRAND = {
    name: "Clínica Demo (TBD)",
    shortName: "Clínica Demo"
  };

  window.__BRAND__ = BRAND;

  function apply(root) {
    var nodes = root.querySelectorAll("[data-brand-name]");
    for (var i = 0; i < nodes.length; i += 1) {
      nodes[i].textContent = BRAND.name;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      apply(document);
    });
  } else {
    apply(document);
  }
})();
