import type { ReactNode } from "react"

import { Carte } from "@/components/commun/mise-en-page"
import { Badge } from "@/components/ui/badge"
import { ecrireValeur, lireValeur, type Champ, type Groupe } from "@/lib/schema-formulaire"

import { CaseACocher, ChampNombre, ChampTexte, Curseur, Liste, Segments } from "./controles"

type Modifier = (chemin: string[], valeur: unknown) => void

/** Une carte pour les champs de premier niveau, puis une carte par groupe du schéma. */
export function FormulaireGenere({
  groupe,
  valeurs,
  onChange,
  titreGeneral,
  complementGeneral,
}: {
  groupe: Groupe
  valeurs: Record<string, unknown>
  onChange: (valeurs: Record<string, unknown>) => void
  titreGeneral: string
  complementGeneral?: ReactNode
}) {
  const modifier: Modifier = (chemin, valeur) => onChange(ecrireValeur(valeurs, chemin, valeur))
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      {(groupe.champs.length > 0 || complementGeneral) && (
        <Carte titre={titreGeneral}>
          {groupe.champs.map((champ) => (
            <ChampGenere key={champ.chemin.join(".")} champ={champ} valeurs={valeurs} modifier={modifier} />
          ))}
          {complementGeneral}
        </Carte>
      )}
      {groupe.groupes.map((sousGroupe) => (
        <Carte key={sousGroupe.chemin.join(".")} titre={sousGroupe.titre}>
          <ContenuGroupe groupe={sousGroupe} valeurs={valeurs} modifier={modifier} />
        </Carte>
      ))}
    </div>
  )
}

function ContenuGroupe({ groupe, valeurs, modifier }: { groupe: Groupe; valeurs: Record<string, unknown>; modifier: Modifier }) {
  return (
    <>
      {groupe.champs.map((champ) => (
        <ChampGenere key={champ.chemin.join(".")} champ={champ} valeurs={valeurs} modifier={modifier} />
      ))}
      {groupe.groupes.map((sousGroupe) => (
        <div key={sousGroupe.chemin.join(".")} className="flex flex-col gap-3 rounded-[14px] bg-[var(--v-beige-2)] p-3.5">
          <h3 className="m-0 text-xs font-semibold uppercase tracking-[.06em] text-[color:var(--v-text-3)]">{sousGroupe.titre}</h3>
          <ContenuGroupe groupe={sousGroupe} valeurs={valeurs} modifier={modifier} />
        </div>
      ))}
      {groupe.description && <p className="m-0 text-xs text-[color:var(--v-text-3)]">{groupe.description}</p>}
    </>
  )
}

function Ligne({ titre, description, children }: { titre: string; description?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
      <span className="flex flex-col">
        <span className="font-semibold">{titre}</span>
        {description && <span className="text-xs text-[color:var(--v-text-3)]">{description}</span>}
      </span>
      {children}
    </div>
  )
}

function ChampGenere({ champ, valeurs, modifier }: { champ: Champ; valeurs: Record<string, unknown>; modifier: Modifier }) {
  const valeur = lireValeur(valeurs, champ.chemin)
  const changer = (nouvelle: unknown) => modifier(champ.chemin, nouvelle)
  const controle = champ.controle
  switch (controle.type) {
    case "case":
      return <CaseACocher libelle={champ.titre} description={champ.description} coche={valeur === true} onChange={changer} />
    case "segments":
      return (
        <Ligne titre={champ.titre} description={champ.description}>
          <Segments libelle={champ.titre} options={controle.options} valeur={valeur} onChange={changer} />
        </Ligne>
      )
    case "liste":
      return (
        <Ligne titre={champ.titre} description={champ.description}>
          <Liste libelle={champ.titre} options={controle.options} valeur={valeur} onChange={changer} className="w-[260px]" />
        </Ligne>
      )
    case "curseur":
      return <Curseur libelle={champ.titre} min={controle.min} max={controle.max} pas={controle.pas} valeur={valeur} onChange={changer} />
    case "nombre":
      return (
        <Ligne titre={champ.titre} description={champ.description}>
          <ChampNombre libelle={champ.titre} min={controle.min} max={controle.max} valeur={valeur} onChange={changer} />
        </Ligne>
      )
    case "texte":
      return (
        <Ligne titre={champ.titre} description={champ.description}>
          <ChampTexte
            libelle={champ.titre}
            masquerLibelle
            valeur={typeof valeur === "string" ? valeur : ""}
            onChange={changer}
            className="w-[260px]"
          />
        </Ligne>
      )
    case "fige":
      return (
        <Ligne titre={champ.titre} description={champ.description}>
          <Badge variant="pink-soft">{controle.libelles[String(valeur)] ?? String(valeur ?? "—")} · imposé</Badge>
        </Ligne>
      )
  }
}
