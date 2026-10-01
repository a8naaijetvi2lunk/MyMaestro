import { useEffect } from "react"

import { api } from "@/api/client"
import { useDonnees } from "@/api/hooks"
import { exiger } from "@/api/requetes"
import { Coquille } from "@/components/coquille/Coquille"
import { EtapesProjet } from "@/components/coquille/EtapesProjet"
import { naviguer, useRoute } from "@/lib/use-route"
import { PageBibliotheque } from "@/pages/PageBibliotheque"
import { PageFile } from "@/pages/PageFile"
import { PageMoteurs } from "@/pages/PageMoteurs"
import { PageProjet } from "@/pages/PageProjet"
import { PageProjets } from "@/pages/PageProjets"
import { PageRecettes } from "@/pages/PageRecettes"

const CLE_REDIRECTION = "mymaestro.redirection-moteurs"

// Repli quand sessionStorage est indisponible : la redirection reste unique tant que la page n'est pas rechargée.
let redirigeEnMemoire = false

function dejaRedirige(): boolean {
  if (redirigeEnMemoire) return true
  try {
    return window.sessionStorage.getItem(CLE_REDIRECTION) === "1"
  } catch {
    return false
  }
}

function noterRedirection(): void {
  redirigeEnMemoire = true
  try {
    window.sessionStorage.setItem(CLE_REDIRECTION, "1")
  } catch {
    // stockage indisponible : le repli en mémoire ci-dessus tient lieu de mémoire
  }
}

export default function App() {
  const route = useRoute()
  const { donnees: moteurs } = useDonnees("moteurs-demarrage", () => exiger(api.GET("/api/moteurs")))
  const aInstaller = moteurs !== null && moteurs.requis_manquants && !moteurs.mode_demo
  const surProjets = route.page === "projets"

  // Premier lancement : un moteur requis manque, on amène sur l'écran « Moteurs » (une seule fois par session).
  useEffect(() => {
    if (aInstaller && surProjets && !dejaRedirige()) {
      noterRedirection()
      naviguer({ page: "moteurs" })
    }
  }, [aInstaller, surProjets])

  const contexte = route.page === "projet" ? <EtapesProjet projetId={route.projetId} etape={route.etape} /> : undefined
  return (
    <Coquille route={route} contexte={contexte}>
      {route.page === "projets" && <PageProjets />}
      {route.page === "projet" && <PageProjet projetId={route.projetId} etape={route.etape} />}
      {route.page === "bibliotheque" && <PageBibliotheque />}
      {route.page === "recettes" && <PageRecettes recetteId={route.recetteId} />}
      {route.page === "file" && <PageFile />}
      {route.page === "moteurs" && <PageMoteurs />}
    </Coquille>
  )
}
