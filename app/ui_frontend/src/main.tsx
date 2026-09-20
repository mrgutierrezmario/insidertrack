import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

// index.html guarantees #root exists; failing at boot with "container missing"
// is the right behavior. Cast keeps `createRoot` happy without a runtime check.
const container = document.getElementById("root") as HTMLElement;

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
