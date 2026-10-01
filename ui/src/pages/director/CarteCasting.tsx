import { useState } from "react"

import type { FicheBibliotheque, Projet } from "@/api/client"
import { actionsDirector } from "@/api/director"
import { Carte } from "@/components/commun/mise-en-page"
import { CaseACocher } from "@/components/formulaire/controles"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const TEINTES_FICHE: Record<string, "pink-soft" | "blue-soft" | "olive-soft"> = { personnage: "pink-soft", decor: "blue-soft", style: "olive-soft" }

/** Bascules de fiches (boutons pressés), comme le choix du casting à la création du projet. */
export function ChoixFiches({ fiches, choisies, basculer, occupe }: { fiches: FicheBibliotheque[]; choisies: string[]; basculer: (id: string) => void; occupe?: boolean }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {fiches.map((fiche) => {
        const choisie = choisies.includes(fiche.id)
        return (
          <button
            key={fiche.id}
            type="button"
            aria-pressed={choisie}
            disabled={occupe}
            onClick={() => basculer(fiche.id)}
            className={cn(
              "h-8 rounded-full px-3 text-xs disabled:opacity-60",
              choisie ? "bg-[var(--v-ink)] font-semibold text-[color:var(--v-on-ink)]" : "bg-[var(--v-beige)] text-foreground",
            )}
          >
            {fiche.nom}
          </button>
        )
      })}
    </div>
  )
}

/** Casting du projet, modifiable après la création : les images des fiches servent de références aux images des plans. */
export function CarteCasting({
  projet,
  fiches,
  executer,
}: {
  projet: Projet
  fiches: FicheBibliotheque[]
  executer: (action: () => Promise<unknown>) => Promise<boolean>
}) {
  const [edition, setEdition] = useState(false)
  const [choix, setChoix] = useState<string[]>(projet.casting)
  const [ajouterAuxPlans, setAjouterAuxPlans] = useState(true)
  const casting = fiches.filter((f) => projet.casting.includes(f.id))
  const nouvelles = choix.filter((id) => !projet.casting.includes(id))
  const avecPlans = projet.plans.length > 0

  function ouvrir() {
    setChoix(projet.casting)
    setEdition(true)
  }

  async function sauver() {
    const ok = await executer(() => actionsDirector.casting(projet.id, choix, avecPlans && ajouterAuxPlans))
    if (ok) setEdition(false)
  }

  return (
    <Carte
      titre="Casting"
      actions={
        edition ? (
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => setEdition(false)}>
              Annuler
            </Button>
            <Button size="sm" variant="accent" onClick={() => void sauver()}>
              Enregistrer
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={ouvrir}>
            Modifier
          </Button>
        )
      }
    >
      {edition ? (
        <div className="flex flex-col gap-3">
          {fiches.length === 0 ? (
            <p className="m-0 text-sm">La bibliothèque est vide : crée d'abord une fiche (personnage, décor ou style).</p>
          ) : (
            <ChoixFiches fiches={fiches} choisies={choix} basculer={(id) => setChoix(choix.includes(id) ? choix.filter((f) => f !== id) : [...choix, id])} />
          )}
          {avecPlans && nouvelles.length > 0 && (
            <CaseACocher
              libelle="Ajouter les nouvelles fiches à tous les plans"
              description="Retire-les ensuite des plans où elles ne sont pas à l'image (détail du plan, écran Prompts)."
              coche={ajouterAuxPlans}
              onChange={setAjouterAuxPlans}
            />
          )}
          {avecPlans && <p className="m-0 text-xs text-[color:var(--v-text-3)]">Une fiche retirée du casting quitte aussi tous les plans.</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1.5">
            {casting.length === 0 ? (
              <span className="text-sm">Aucune fiche : sans casting, les images des plans n'ont pas de référence.</span>
            ) : (
              casting.map((fiche) => (
                <Badge key={fiche.id} variant={TEINTES_FICHE[fiche.type] ?? "default"}>
                  {fiche.nom}
                </Badge>
              ))
            )}
          </div>
        </div>
      )}
    </Carte>
  )
}
