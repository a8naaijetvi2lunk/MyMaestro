import { useState } from "react"

import type { LigneParoles, Section } from "@/api/client"
import { actionsDirector } from "@/api/director"
import { useAction } from "@/api/use-action"
import { Alerte, Carte } from "@/components/commun/mise-en-page"
import { Button } from "@/components/ui/button"
import { formatDecimal, formatDuree } from "@/lib/format"
import { versHash } from "@/lib/route"
import { naviguer } from "@/lib/use-route"
import { cn } from "@/lib/utils"

import type { ProprietesEcran } from "./commun"

export function EcranAnalyse({ projet, director, recharger }: ProprietesEcran) {
  const { erreur, enCours, executer } = useAction(recharger)
  const etat = projet.etat_phases.analyse
  const analyse = director?.analyse ?? null
  const enAnalyse = etat === "en_cours"
  const lancer = () => void executer(() => actionsDirector.lancer(projet.id, "analyse"))

  const bandeau = (
    <>
      {enAnalyse && <p className="m-0 text-sm">Analyse en cours dans la file GPU…</p>}
      {etat === "echec" && <Alerte>{director?.erreurs.analyse ?? "L'analyse a échoué."}</Alerte>}
    </>
  )

  if (!analyse) {
    return (
      <Carte titre="Analyse">
        {bandeau}
        {!enAnalyse && (
          <div>
            <Button variant="accent" disabled={!projet.chanson || enCours} onClick={lancer}>
              {etat === "echec" ? "Relancer l'analyse" : "Lancer l'analyse"}
            </Button>
          </div>
        )}
        {erreur && <Alerte>{erreur}</Alerte>}
      </Carte>
    )
  }

  const duree = projet.duree_chanson_s ?? analyse.sections[analyse.sections.length - 1]?.fin_s ?? 0

  return (
    <div className="flex flex-col gap-4">
      {bandeau}
      <Carte titre="Structure">
        <p className="m-0 text-sm text-[color:var(--v-text-2)]">
          {formatDecimal(analyse.bpm, 0)} BPM · {analyse.sections.length} sections · {analyse.lignes.length} lignes de paroles
          {analyse.simule && " · analyse simulée (mode démo : aucun moteur réel lancé)"}
        </p>
        <BandeauSections sections={analyse.sections} voix={analyse.voix} duree={duree} />
      </Carte>
      <CalageEtValidation
        key={JSON.stringify(analyse.lignes)}
        lignes={analyse.lignes}
        occupe={enCours || enAnalyse}
        validable={etat === "a_valider"}
        termine={etat === "termine"}
        enregistrer={(lignes) => void executer(() => actionsDirector.lignes(projet.id, lignes))}
        valider={async () => {
          if (await executer(() => actionsDirector.valider(projet.id, "analyse"))) {
            naviguer({ page: "projet", projetId: projet.id, etape: "ecriture" })
          }
        }}
        relancer={projet.plans.length === 0 ? lancer : undefined}
        libelleRelance={etat === "echec" ? "Relancer l'analyse" : "Refaire l'analyse"}
        lienEcriture={versHash({ page: "projet", projetId: projet.id, etape: "ecriture" })}
        erreur={erreur}
      />
    </div>
  )
}

interface ProprietesCalage {
  lignes: LigneParoles[]
  occupe: boolean
  validable: boolean
  termine: boolean
  enregistrer: (lignes: LigneParoles[]) => void
  valider: () => void
  relancer?: () => void
  libelleRelance: string
  lienEcriture: string
  erreur: string | null
}

function CalageEtValidation({ lignes, occupe, validable, termine, enregistrer, valider, relancer, libelleRelance, lienEcriture, erreur }: ProprietesCalage) {
  const [brouillon, setBrouillon] = useState<LigneParoles[]>(lignes)
  const modifie = JSON.stringify(brouillon) !== JSON.stringify(lignes)

  return (
    <>
      <EditeurLignes lignes={brouillon} modifie={modifie} setLignes={setBrouillon} enregistrer={() => enregistrer(brouillon)} occupe={occupe} />
      {erreur && <Alerte>{erreur}</Alerte>}
      <div className="flex flex-wrap items-center gap-3">
        {validable && (
          <Button variant="accent" disabled={occupe || modifie} onClick={() => void valider()}>
            Valider l'analyse et ouvrir l'écriture
          </Button>
        )}
        {validable && modifie && <span className="text-sm text-[color:var(--v-text-2)]">Enregistre d'abord le calage.</span>}
        {termine && <a href={lienEcriture}>Aller à l'écriture →</a>}
        {relancer && (
          <Button variant="ghost" disabled={occupe} onClick={relancer}>
            {libelleRelance}
          </Button>
        )}
      </div>
    </>
  )
}

function BandeauSections({ sections, voix, duree }: { sections: Section[]; voix: Section[]; duree: number }) {
  if (duree <= 0) return null
  const chantee = (section: Section) => voix.some((v) => v.debut_s <= section.debut_s && section.fin_s <= v.fin_s)
  return (
    <div className="flex h-12 w-full overflow-hidden rounded-[12px]">
      {sections.map((section) => (
        <div
          key={`${section.nom}-${section.debut_s}`}
          title={`${section.nom} · ${formatDuree(section.debut_s)} → ${formatDuree(section.fin_s)}`}
          style={{ width: `${((section.fin_s - section.debut_s) / duree) * 100}%` }}
          className={cn(
            "flex items-center justify-center border-r-2 border-card text-xs font-semibold",
            chantee(section) ? "bg-[var(--v-pink-soft)] text-[color:var(--v-accent-ink)]" : "bg-[var(--v-beige)] text-[color:var(--v-text-2)]",
          )}
        >
          {section.nom}
        </div>
      ))}
    </div>
  )
}

function EditeurLignes({
  lignes,
  modifie,
  setLignes,
  enregistrer,
  occupe,
}: {
  lignes: LigneParoles[]
  modifie: boolean
  setLignes: (mise_a_jour: (actuelles: LigneParoles[]) => LigneParoles[]) => void
  enregistrer: () => void
  occupe: boolean
}) {
  function changer(indice: number, champ: keyof LigneParoles, valeur: string) {
    setLignes((actuelles) =>
      actuelles.map((ligne, i) => (i !== indice ? ligne : { ...ligne, [champ]: champ === "texte" ? valeur : Number(valeur) })),
    )
  }

  return (
    <Carte
      titre="Paroles calées sur la voix"
      actions={
        <Button variant="outline" size="sm" disabled={!modifie || occupe} onClick={enregistrer}>
          Enregistrer le calage
        </Button>
      }
    >
      {lignes.length === 0 ? (
        <p className="m-0 text-sm">Aucune ligne détectée.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-[color:var(--v-text-3)]">
            <tr>
              <th scope="col" className="py-2">Paroles</th>
              <th scope="col" className="w-28">Début (s)</th>
              <th scope="col" className="w-28">Fin (s)</th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((ligne, indice) => (
              <tr key={indice} className="border-t border-[var(--v-beige)]">
                <td className="py-1.5 pr-3">
                  <input
                    aria-label={`Paroles de la ligne ${indice + 1}`}
                    value={ligne.texte}
                    onChange={(e) => changer(indice, "texte", e.target.value)}
                    className="h-9 w-full rounded-[10px] border-0 bg-[var(--v-beige-2)] px-2.5"
                  />
                </td>
                {(["debut_s", "fin_s"] as const).map((champ) => (
                  <td key={champ} className="pr-2">
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      aria-label={`${champ === "debut_s" ? "Début" : "Fin"} de la ligne ${indice + 1}`}
                      value={ligne[champ]}
                      onChange={(e) => changer(indice, champ, e.target.value)}
                      className="h-9 w-24 rounded-[10px] border-0 bg-[var(--v-beige-2)] px-2.5 tabular-nums"
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Carte>
  )
}
