import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { PeriodProvider } from "./app/PeriodContext";
import AppErrorBoundary from "./components/AppErrorBoundary";

import "./index.css"; // reset + base
import "./styles/fonts.css";
import "./styles/mugo.tokens.css";
import "./styles/design-system.css";
import "./styles/App.css";
import "./styles/shell.css";

function renderBootstrapFallback(message: string) {
  const container = document.createElement("div");
  container.style.minHeight = "100vh";
  container.style.display = "grid";
  container.style.placeItems = "center";
  container.style.padding = "24px";
  container.style.background =
    "radial-gradient(900px 360px at 12% -10%, rgba(215,219,106,.24), transparent 62%), #f2f0ec";

  const card = document.createElement("div");
  card.style.width = "min(560px, 100%)";
  card.style.padding = "24px";
  card.style.borderRadius = "20px";
  card.style.background = "rgba(255,255,255,.92)";
  card.style.boxShadow = "0 18px 52px rgba(15, 23, 42, .10)";

  const title = document.createElement("h1");
  title.textContent = "Mugô Dados";
  title.style.margin = "0 0 10px";

  const text = document.createElement("p");
  text.textContent = message;
  text.style.margin = "0";
  text.style.color = "rgba(15, 23, 42, .74)";

  card.append(title, text);
  container.append(card);
  document.body.replaceChildren(container);
}

const rootElement = document.getElementById("root");

if (!rootElement) {
  const message = 'Container "#root" nao encontrado no index.html.';
  console.error("[app-bootstrap]", message);
  renderBootstrapFallback(message);
} else {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <AppErrorBoundary>
        <PeriodProvider>
          <App />
        </PeriodProvider>
      </AppErrorBoundary>
    </React.StrictMode>
  );
}
