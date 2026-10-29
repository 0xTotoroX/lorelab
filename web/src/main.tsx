import React from "react";
import ReactDOM from "react-dom/client";
import { SettingsApp } from "./settings/SettingsApp";
import "./theme.css";
import "./settings/settings.css";
import "./settings/layouts.css";
import "./settings/responsive.css";
import "./settings/flow.css";
import "./settings/obsidian-tokens.css";
import "./settings/unified.css";
import "./settings/diagnostic-groups.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><SettingsApp /></React.StrictMode>,
);
