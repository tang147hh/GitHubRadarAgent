import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ContentIndexProvider } from "./hooks/useContentIndexData";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ContentIndexProvider><App /></ContentIndexProvider>
  </React.StrictMode>,
);
