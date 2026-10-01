import type { ReactNode } from "react"

import type { EtatDirector, Projet } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { libelleEtatPhase } from "@/lib/format"

export type ProprietesEcran = { projet: Projet; director: EtatDirector | null; recharger: () => void }

export function BadgeEtatPhase({ etat }: { etat: string | undefined }) {
  if (!etat) return null
  const variante = etat === "termine" ? "olive-soft" : etat === "echec" ? "danger" : etat === "a_valider" ? "pink-soft" : etat === "en_cours" ? "yellow-soft" : "default"
  return <Badge variant={variante}>{libelleEtatPhase(etat)}</Badge>
}

/** Barre d'actions en pied d'écran (maquette 3). */
export function BarreActions({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[60px] flex-wrap items-center gap-3 rounded-full bg-card px-5 py-2.5 text-[13px] text-card-foreground">
      {children}
    </div>
  )
}
