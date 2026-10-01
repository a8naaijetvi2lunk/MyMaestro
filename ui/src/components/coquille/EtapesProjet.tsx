import { Check } from "lucide-react"

import { api } from "@/api/client"
import { useDonnees, useRechargementSurEvenements } from "@/api/hooks"
import { exiger } from "@/api/requetes"
import { ETAPES, etapeCourante } from "@/lib/etapes"
import { versHash } from "@/lib/route"
import { cn } from "@/lib/utils"

/** Étapes du projet ouvert, dans la barre latérale (maquettes 2 et 3). */
export function EtapesProjet({ projetId, etape }: { projetId: string; etape: string | null }) {
  const { donnees: projet, recharger } = useDonnees(`etapes:${projetId}`, () =>
    exiger(api.GET("/api/projets/{projet_id}", { params: { path: { projet_id: projetId } } })),
  )
  useRechargementSurEvenements(recharger)
  const courante = etape && ETAPES.some((e) => e.id === etape) ? etape : projet ? etapeCourante(projet.etat_phases) : null

  return (
    <div className="flex flex-col gap-2">
      <span className="truncate px-3 text-[11px] uppercase tracking-[.08em] text-[color:var(--sidebar-muted)]">
        {projet?.titre ?? "Projet"}
      </span>
      <ol className="m-0 flex list-none flex-col gap-0.5 p-0">
        {ETAPES.map((e) => {
          const etat = projet?.etat_phases[e.id]
          const active = e.id === courante
          const contenu = (
            <>
              <Pastille etat={etat} active={active} />
              {e.libelle}
            </>
          )
          return (
            <li key={e.id}>
              {e.disponible ? (
                <a
                  href={versHash({ page: "projet", projetId, etape: e.id })}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-[34px] items-center gap-2.5 rounded-[10px] px-3 text-[13px] no-underline",
                    active ? "bg-[var(--structure-quiet)] font-semibold text-sidebar-foreground" : "text-[color:var(--structure-text)] hover:bg-[var(--structure-quiet)]",
                  )}
                >
                  {contenu}
                </a>
              ) : (
                <span
                  title="Pas encore disponible"
                  className="flex h-[34px] items-center gap-2.5 px-3 text-[13px] text-[color:var(--sidebar-muted)] opacity-70"
                >
                  {contenu}
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Pastille({ etat, active }: { etat: string | undefined; active: boolean }) {
  if (etat === "termine") {
    return (
      <span className="flex size-[18px] shrink-0 items-center justify-center rounded-full bg-[var(--v-olive)]">
        <Check aria-hidden="true" className="size-[11px] text-[color:var(--v-structure)]" strokeWidth={3} />
      </span>
    )
  }
  if (etat === "echec") return <span className="size-[18px] shrink-0 rounded-full bg-[var(--v-danger)]" />
  if (active || etat === "en_cours" || etat === "a_valider") {
    return (
      <span className="size-[18px] shrink-0 rounded-full bg-[var(--v-pink)] [box-shadow:0_0_0_4px_color-mix(in_srgb,var(--v-pink)_25%,transparent)]" />
    )
  }
  return <span className="size-[18px] shrink-0 rounded-full border-2 border-[var(--structure-line)]" />
}
