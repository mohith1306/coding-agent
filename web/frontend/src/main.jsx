import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles/global.css";
import "./styles/theme.css";
import "./styles/layout.css";
import "./styles/editor.css";
import "./styles/chat.css";
import "./styles/picker.css";
import "./styles/markdown.css";
import "./styles/terminal.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
