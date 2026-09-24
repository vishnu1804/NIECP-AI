import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// register the service worker (PWA, spec §40)
if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
