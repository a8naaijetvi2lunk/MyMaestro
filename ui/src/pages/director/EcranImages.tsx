import type { MoteurImage } from "@/api/client"
import { actionsDirector, urlMediaProjet } from "@/api/director"
import { useAction } from "@/api/use-action"
import { Alerte, Carte } from "@/components/commun/mise-en-page"
import { Liste } from "@/components/formulaire/controles"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatDecimal, libelleRole } from "@/lib/format"
import { naviguer } from "@/lib/use-route"
import { cn } from "@/lib/utils"

import { BarreActions, type ProprietesEcran } from "./commun"

const OPTIONS_IMAGE = [
  { valeur: "qwen_image_edit_2511_20B_fp8_lightning_8step", libelle: "Qwen" },
  { valeur: "codex_imagegen", libelle: "Codex" },
]

export function EcranImages({ projet, director, recharger }: ProprietesEcran) {
  const { erreur, enCours, executer } = useAction(recharger)
  const etat = projet.etat_phases.images
  const lancee = etat !== undefined && etat !== "a_faire"
  const promptsValides = projet.etat_phases.prompts === "termine"
  const refaisable = etat === "en_cours" || etat === "a_valider" || etat === "echec"

  if (projet.plans.length === 0) {
    return (
      <Carte titre="Images de départ">
        <p className="m-0 text-sm">Aucun plan : termine d'abord l'écriture et les prompts.</p>
      </Carte>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {projet.plans.map((plan) => (
          <article key={plan.id} className="flex flex-col gap-2.5 rounded-[var(--r-card)] bg-card p-3.5 text-card-foreground">
            <div
              className={cn(
                "flex items-center justify-center overflow-hidden rounded-[14px] bg-[var(--v-beige)] text-xs text-[color:var(--v-text-3)]",
                projet.format === "9:16" ? "aspect-[9/16]" : "aspect-video",
              )}
            >
              {plan.image_depart ? (
                <img src={urlMediaProjet(projet.id, plan.image_depart)} alt={`Image de départ du plan ${plan.indice + 1}`} className="size-full object-cover" />
              ) : etat === "en_cours" ? (
                "Image en attente…"
              ) : etat === "a_valider" || etat === "echec" ? (
                "Échec — à refaire"
              ) : etat === "termine" ? (
                "Aucune image"
              ) : (
                "Pas encore générée"
              )}
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-bold">Plan {plan.indice + 1}</span>
              <Badge variant={plan.role === "chante" ? "pink-soft" : "blue-soft"}>
                {libelleRole(plan.role)} · {formatDecimal(plan.duree_s)} s
              </Badge>
            </div>
            <p className="m-0 line-clamp-2 text-xs text-[color:var(--v-text-2)]">{plan.paroles ? `« ${plan.paroles} »` : plan.description}</p>
            <div className="mt-auto flex flex-wrap items-center gap-2">
              <Liste
                libelle={`Moteur d'image du plan ${plan.indice + 1}`}
                options={OPTIONS_IMAGE}
                valeur={plan.moteur_image ?? ""}
                onChange={(valeur) => void executer(() => actionsDirector.modifierPlan(projet.id, plan.id, { moteur_image: valeur as MoteurImage }))}
                className="h-8 w-[110px]"
              />
              <Button size="sm" variant="outline" disabled={!refaisable || enCours} onClick={() => void executer(() => actionsDirector.refaireImage(projet.id, plan.id))}>
                Refaire cette image
              </Button>
            </div>
          </article>
        ))}
      </div>
      {director?.erreurs.images && <Alerte>{director.erreurs.images}</Alerte>}
      {erreur && <Alerte>{erreur}</Alerte>}
      <BarreActions>
        <span className="text-[color:var(--v-text-2)]">
          {projet.plans.filter((p) => p.image_depart).length} / {projet.plans.length} images · ensuite : vidéo et timeline
        </span>
        {!lancee && !promptsValides && (
          <Button variant="ghost" className="ml-auto" onClick={() => naviguer({ page: "projet", projetId: projet.id, etape: "prompts" })}>
            Valide d'abord les prompts
          </Button>
        )}
        {!lancee && promptsValides && (
          <Button variant="outline" className="ml-auto" disabled={enCours} onClick={() => void executer(() => actionsDirector.lancer(projet.id, "images"))}>
            Générer les images
          </Button>
        )}
        <Button variant="accent" className={lancee ? "ml-auto" : undefined} disabled={enCours || etat !== "a_valider"} onClick={() => void executer(() => actionsDirector.valider(projet.id, "images"))}>
          Valider les images
        </Button>
        {etat === "termine" && (
          <Button variant="outline" onClick={() => naviguer({ page: "projet", projetId: projet.id, etape: "video" })}>
            Ouvrir la timeline
          </Button>
        )}
      </BarreActions>
    </div>
  )
}
