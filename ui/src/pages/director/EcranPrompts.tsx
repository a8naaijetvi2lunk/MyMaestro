import { Fragment, useState } from "react"

import { api, type CompatibiliteMoteur, type FicheBibliotheque, type MoteurImage, type MoteurVideo, type Plan, type PlanModification } from "@/api/client"
import { actionsDirector } from "@/api/director"
import { useDonnees } from "@/api/hooks"
import { exiger, urlMedia } from "@/api/requetes"
import { useAction } from "@/api/use-action"
import { Alerte, Carte } from "@/components/commun/mise-en-page"
import { Liste } from "@/components/formulaire/controles"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { indicationMoteur, LIBELLES_COURTS_VIDEO, resumeMoteurs } from "@/lib/etapes"
import { formatDecimal, formatDuree, libelleRole } from "@/lib/format"
import { naviguer } from "@/lib/use-route"
import { cn } from "@/lib/utils"

import { CarteCasting, ChoixFiches } from "./CarteCasting"
import { BarreActions, type ProprietesEcran } from "./commun"

const MOTEURS_VIDEO: MoteurVideo[] = ["minimax_h3", "ltx2_22B_distilled_1_1_omninft", "ltx2_25_omninft"]
const OPTIONS_IMAGE = [
  { valeur: "qwen_image_edit_2511_20B_fp8_lightning_8step", libelle: "Qwen" },
  { valeur: "codex_imagegen", libelle: "Codex" },
]

export function EcranPrompts({ projet, director, recharger }: ProprietesEcran) {
  const { erreur, enCours, executer } = useAction(recharger)
  const [ouvert, setOuvert] = useState<string | null>(null)
  const signature = projet.plans.map((p) => `${p.id}:${p.images}:${p.moteur_video}`).join("|")
  const { donnees: compatibilites } = useDonnees(`compat:${projet.id}:${signature}`, () => actionsDirector.compatibilites(projet.id))
  const { donnees: fiches } = useDonnees("bibliotheque", () => exiger(api.GET("/api/bibliotheque")))
  const etat = projet.etat_phases.prompts
  const casting = (fiches ?? []).filter((f) => projet.casting.includes(f.id))

  if (projet.plans.length === 0) {
    return (
      <Carte titre="Prompts et moteurs">
        <p className="m-0 text-sm">Aucun plan : écris et valide d'abord le découpage.</p>
        {director?.erreurs.prompts && <Alerte>{director.erreurs.prompts}</Alerte>}
        {director?.erreurs.bascule && <Alerte>Bascule sur Claude : {director.erreurs.bascule}</Alerte>}
      </Carte>
    )
  }

  const modifier = (planId: string, modification: PlanModification) =>
    void executer(() => actionsDirector.modifierPlan(projet.id, planId, modification))

  async function validerEtGenerer() {
    if (await executer(() => actionsDirector.valider(projet.id, "prompts"))) {
      naviguer({ page: "projet", projetId: projet.id, etape: "images" })
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {etat === "en_cours" && <p className="m-0 text-sm text-[color:var(--v-text-2)]">Prompts en cours d'écriture dans la file…</p>}
      {director?.erreurs.prompts && <Alerte>{director.erreurs.prompts}</Alerte>}
      {director?.erreurs.bascule && <Alerte>Bascule sur Claude : {director.erreurs.bascule}</Alerte>}
      <CarteCasting key={projet.casting.join("|")} projet={projet} fiches={fiches ?? []} executer={executer} />
      <section aria-label="Plans" className="overflow-x-auto rounded-[var(--r-card)] bg-card px-4 py-3 text-card-foreground">
        <table className="w-full min-w-[1080px] table-fixed border-collapse text-[13px]">
          <colgroup>
            <col className="w-9" />
            <col className="w-24" />
            <col className="w-32" />
            <col className="w-60" />
            <col />
            <col className="w-36" />
            <col className="w-60" />
          </colgroup>
          <thead>
            <tr className="text-left text-xs text-[color:var(--v-text-3)]">
              <th scope="col" className="py-2 font-semibold">#</th>
              <th scope="col" className="font-semibold">Rôle</th>
              <th scope="col" className="font-semibold">Début · durée</th>
              <th scope="col" className="font-semibold">Paroles / description</th>
              <th scope="col" className="font-semibold">Prompt vidéo</th>
              <th scope="col" className="font-semibold">Image</th>
              <th scope="col" className="font-semibold">Moteur vidéo</th>
            </tr>
          </thead>
          <tbody>
            {projet.plans.map((plan) => (
              <Fragment key={plan.id}>
                <LignePlan
                  plan={plan}
                  compatibilites={compatibilites?.[plan.id] ?? []}
                  ouvert={ouvert === plan.id}
                  basculer={() => setOuvert(ouvert === plan.id ? null : plan.id)}
                  modifier={(modification) => modifier(plan.id, modification)}
                  occupe={enCours}
                />
                {ouvert === plan.id && (
                  <tr>
                    <td colSpan={7} className="pb-3">
                      <DetailPlan plan={plan} casting={casting} occupe={enCours} modifier={(modification) => modifier(plan.id, modification)} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>
      {erreur && <Alerte>{erreur}</Alerte>}
      <BarreActions>
        <span className="text-[color:var(--v-text-2)]">{resumeMoteurs(projet.plans)}</span>
        <Button
          variant="outline"
          className="ml-auto"
          disabled={enCours || etat === "en_cours"}
          onClick={() => void executer(() => actionsDirector.lancer(projet.id, "prompts"))}
        >
          {etat === "a_faire" ? "Générer les prompts" : "Régénérer les prompts"}
        </Button>
        <Button variant="accent" disabled={enCours || etat !== "a_valider"} onClick={() => void validerEtGenerer()}>
          Valider et générer les images
        </Button>
      </BarreActions>
    </div>
  )
}

function LignePlan({
  plan,
  compatibilites,
  ouvert,
  basculer,
  modifier,
  occupe,
}: {
  plan: Plan
  compatibilites: CompatibiliteMoteur[]
  ouvert: boolean
  basculer: () => void
  modifier: (modification: PlanModification) => void
  occupe: boolean
}) {
  const indication = indicationMoteur(compatibilites, plan.moteur_video)
  return (
    <tr className={cn("h-[58px] border-t border-[var(--v-beige)]", ouvert && "bg-[var(--v-beige-2)]")}>
      <td className="font-bold">{plan.indice + 1}</td>
      <td>
        <Badge variant={plan.role === "chante" ? "pink-soft" : "blue-soft"}>{libelleRole(plan.role)}</Badge>
      </td>
      <td className="tabular-nums">
        {formatDuree(plan.debut_s)} · {formatDecimal(plan.duree_s)} s
      </td>
      <td className={cn("pr-3", plan.paroles ? "italic" : "text-[color:var(--v-text-2)]")}>{plan.paroles ? `« ${plan.paroles} »` : plan.description}</td>
      <td className="pr-3">
        <button
          type="button"
          aria-expanded={ouvert}
          onClick={basculer}
          className="w-full truncate bg-transparent p-0 text-left text-[color:var(--v-text-2)] hover:text-foreground"
        >
          {plan.prompt_video || "— (déplier pour écrire)"}
        </button>
      </td>
      <td>
        <Liste
          libelle={`Moteur d'image du plan ${plan.indice + 1}`}
          options={OPTIONS_IMAGE}
          valeur={plan.moteur_image ?? ""}
          onChange={(valeur) => modifier({ moteur_image: valeur as MoteurImage })}
          className="h-8 w-[136px]"
        />
      </td>
      <td>
        <div className="flex flex-col gap-1">
          <div role="group" aria-label={`Moteur vidéo du plan ${plan.indice + 1}`} className="flex gap-1">
            {MOTEURS_VIDEO.map((moteur) => {
              const compat = compatibilites.find((c) => c.moteur === moteur)
              const indisponible = compat ? !compat.compatible : false
              const actif = plan.moteur_video === moteur
              return (
                <button
                  key={moteur}
                  type="button"
                  aria-pressed={actif}
                  disabled={indisponible || occupe}
                  title={compat?.note ?? undefined}
                  onClick={() => !actif && modifier({ moteur_video: moteur })}
                  className={cn(
                    "h-7 rounded-full px-3 text-xs",
                    actif
                      ? "bg-[var(--v-ink)] font-semibold text-[color:var(--v-on-ink)]"
                      : indisponible
                        ? "bg-[var(--v-beige)] text-[color:var(--v-text-3)] line-through"
                        : "bg-transparent [box-shadow:inset_0_0_0_1px_var(--v-edge)]",
                  )}
                >
                  {LIBELLES_COURTS_VIDEO[moteur]}
                </button>
              )
            })}
          </div>
          {indication && (
            <span className={cn("text-[11px]", indication.alerte ? "text-[color:var(--v-danger-ink)]" : "text-[color:var(--v-text-3)]")}>
              {indication.texte}
            </span>
          )}
        </div>
      </td>
    </tr>
  )
}

function DetailPlan({
  plan,
  casting,
  occupe,
  modifier,
}: {
  plan: Plan
  casting: FicheBibliotheque[]
  occupe: boolean
  modifier: (modification: PlanModification) => void
}) {
  const references = casting.filter((f) => plan.fiches.includes(f.id))
  const basculer = (id: string) => modifier({ fiches: plan.fiches.includes(id) ? plan.fiches.filter((f) => f !== id) : [...plan.fiches, id] })
  return (
    <div className="grid gap-3.5 rounded-[14px] bg-[var(--v-beige-2)] p-3.5 [box-shadow:inset_0_0_0_1px_var(--v-beige)] lg:grid-cols-3">
      <ChampPrompt key={`v-${plan.prompt_video}`} libelle="Prompt vidéo" valeur={plan.prompt_video} enregistrer={(v) => modifier({ prompt_video: v })} />
      <ChampPrompt key={`i-${plan.prompt_image}`} libelle="Prompt image" valeur={plan.prompt_image} enregistrer={(v) => modifier({ prompt_image: v })} />
      <div className="flex flex-col gap-2">
        <ChampPrompt key={`s-${plan.prompt_son}`} libelle="Prompt son" valeur={plan.prompt_son} enregistrer={(v) => modifier({ prompt_son: v })} />
        <span className="text-xs font-semibold text-[color:var(--v-text-3)]">À l'image (références)</span>
        {casting.length === 0 ? (
          <span className="text-xs">Casting vide : ajoute des fiches au casting, en haut de l'écran.</span>
        ) : (
          <ChoixFiches fiches={casting} choisies={plan.fiches} basculer={basculer} occupe={occupe} />
        )}
        <div className="flex flex-wrap gap-2">
          {references.length === 0 && <span className="text-xs">Aucune fiche à l'image : pas de référence pour l'image de ce plan.</span>}
          {references.flatMap((fiche) =>
            fiche.images.length > 0
              ? fiche.images.map((image) => (
                  <img key={image.id} src={urlMedia(image.chemin)} alt={`${fiche.nom} — ${image.role}`} className="h-[84px] w-16 rounded-[10px] object-cover" />
                ))
              : [
                  <span key={fiche.id} className="flex h-[84px] w-16 items-center justify-center rounded-[10px] bg-[var(--v-beige)] p-1 text-center text-[10px]">
                    {fiche.nom}
                  </span>,
                ],
          )}
        </div>
        {plan.role === "chante" && (
          <span className="text-xs text-[color:var(--v-text-2)]">
            Audio : segment {formatDuree(plan.debut_s)} → {formatDuree(plan.debut_s + plan.duree_s)} de la chanson
          </span>
        )}
      </div>
    </div>
  )
}

function ChampPrompt({ libelle, valeur, enregistrer }: { libelle: string; valeur: string; enregistrer: (valeur: string) => void }) {
  const [texte, setTexte] = useState(valeur)
  return (
    <label className="flex flex-col gap-1.5 text-xs font-semibold text-[color:var(--v-text-3)]">
      {libelle}
      <textarea
        rows={4}
        value={texte}
        onChange={(evenement) => setTexte(evenement.target.value)}
        onBlur={() => {
          if (texte !== valeur) enregistrer(texte)
        }}
        className="resize-y rounded-[10px] border-0 bg-card px-2.5 py-2 text-xs font-normal leading-[1.4] text-foreground [box-shadow:inset_0_0_0_1px_var(--v-edge)]"
      />
    </label>
  )
}
