import { useState } from "react"

import { api } from "@/api/client"
import { useDonnees } from "@/api/hooks"
import { exiger } from "@/api/requetes"
import { Alerte, EnTetePage } from "@/components/commun/mise-en-page"
import { FenetreNouveauProjet } from "@/components/projets/FenetreNouveauProjet"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { versHash } from "@/lib/route"

export function PageProjets() {
  const { donnees: projets, erreur } = useDonnees("projets", () => exiger(api.GET("/api/projets")))
  const [creation, setCreation] = useState(false)

  return (
    <div className="flex flex-col gap-5">
      <EnTetePage
        titre="Projets"
        sousTitre="Chaque projet suit les phases du module Director musique."
        actions={
          <Button variant="accent" onClick={() => setCreation(true)}>
            Nouveau projet
          </Button>
        }
      />
      {erreur && <Alerte>{erreur}</Alerte>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(projets ?? []).map((projet) => (
          <a
            key={projet.id}
            href={versHash({ page: "projet", projetId: projet.id, etape: null })}
            className="flex flex-col gap-2 rounded-[var(--r-card)] bg-card p-5 text-card-foreground no-underline hover:shadow-[var(--shadow-float)]"
          >
            <span className="font-cojeev-display text-xl font-bold">{projet.titre}</span>
            <span className="flex flex-wrap items-center gap-2 text-sm text-[color:var(--v-text-3)]">
              <Badge variant="blue-soft">{projet.format}</Badge>
              {projet.nb_plans} plan{projet.nb_plans > 1 ? "s" : ""}
            </span>
          </a>
        ))}
      </div>
      {creation && <FenetreNouveauProjet fermer={() => setCreation(false)} />}
    </div>
  )
}
