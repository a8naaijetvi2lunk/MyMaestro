import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import App from "./App.tsx"
import { appliquerMode, lireMode } from "@/lib/mode"

// Mode clair par défaut (maquettes validées), sombre si l'utilisateur l'a choisi.
appliquerMode(lireMode())

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
