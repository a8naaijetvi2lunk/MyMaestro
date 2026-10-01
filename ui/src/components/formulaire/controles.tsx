import { useId } from "react"

import { formatDecimal } from "@/lib/format"
import type { Option, ValeurOption } from "@/lib/schema-formulaire"
import { cn } from "@/lib/utils"

const FOND_CONTROLE = "border-0 bg-[var(--v-beige)] text-foreground"

export function Segments({
  libelle,
  options,
  valeur,
  onChange,
}: {
  libelle: string
  options: Option[]
  valeur: unknown
  onChange: (valeur: ValeurOption) => void
}) {
  return (
    <div role="group" aria-label={libelle} className="flex w-fit flex-wrap gap-1 rounded-full bg-[var(--v-beige)] p-1">
      {options.map((option) => {
        const actif = option.valeur === valeur
        return (
          <button
            key={String(option.valeur)}
            type="button"
            aria-pressed={actif}
            onClick={() => onChange(option.valeur)}
            className={cn(
              "h-8 rounded-full px-4 text-[13px]",
              actif ? "bg-card font-semibold text-foreground" : "bg-transparent text-[color:var(--v-text-2)] hover:text-foreground",
            )}
          >
            {option.libelle}
          </button>
        )
      })}
    </div>
  )
}

export function CaseACocher({
  libelle,
  description,
  coche,
  onChange,
}: {
  libelle: string
  description?: string
  coche: boolean
  onChange: (coche: boolean) => void
}) {
  return (
    <label className="flex items-center gap-3 text-sm">
      <input
        type="checkbox"
        checked={coche}
        onChange={(evenement) => onChange(evenement.target.checked)}
        className="size-[18px] shrink-0 accent-[var(--v-ink)]"
      />
      <span className="flex flex-col">
        <span className="font-semibold">{libelle}</span>
        {description && <span className="text-xs text-[color:var(--v-text-3)]">{description}</span>}
      </span>
    </label>
  )
}

export function Liste({
  libelle,
  options,
  valeur,
  onChange,
  className,
}: {
  libelle: string
  options: Option[]
  valeur: unknown
  onChange: (valeur: ValeurOption) => void
  className?: string
}) {
  return (
    <select
      aria-label={libelle}
      value={String(valeur ?? "")}
      onChange={(evenement) => {
        const choisie = options.find((option) => String(option.valeur) === evenement.target.value)
        if (choisie) onChange(choisie.valeur)
      }}
      className={cn("h-9 rounded-[12px] px-2.5 text-sm", FOND_CONTROLE, className)}
    >
      {options.map((option) => (
        <option key={String(option.valeur)} value={String(option.valeur)}>
          {option.libelle}
        </option>
      ))}
    </select>
  )
}

export function Curseur({
  libelle,
  min,
  max,
  pas,
  valeur,
  onChange,
}: {
  libelle: string
  min: number
  max: number
  pas: number
  valeur: unknown
  onChange: (valeur: number) => void
}) {
  const id = useId()
  const courant = typeof valeur === "number" ? valeur : min
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[13px] font-semibold">
        {libelle} · {formatDecimal(courant)}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={pas}
        value={courant}
        onChange={(evenement) => onChange(Number(evenement.target.value))}
        className="accent-[var(--v-ink)]"
      />
    </div>
  )
}

export function ChampNombre({
  libelle,
  min,
  max,
  valeur,
  onChange,
}: {
  libelle: string
  min?: number
  max?: number
  valeur: unknown
  onChange: (valeur: number) => void
}) {
  return (
    <input
      type="number"
      aria-label={libelle}
      min={min}
      max={max}
      value={typeof valeur === "number" ? valeur : ""}
      onChange={(evenement) => {
        const nombre = Number(evenement.target.value)
        if (evenement.target.value !== "" && Number.isFinite(nombre)) onChange(nombre)
      }}
      className="h-9 w-[72px] rounded-[12px] border-0 bg-card px-3 text-sm [box-shadow:inset_0_0_0_1px_var(--v-edge)]"
    />
  )
}

export function ChampTexte({
  libelle,
  valeur,
  onChange,
  masquerLibelle = false,
  className,
  autoFocus,
  required,
  placeholder,
}: {
  libelle: string
  valeur: string
  onChange: (valeur: string) => void
  masquerLibelle?: boolean
  className?: string
  autoFocus?: boolean
  required?: boolean
  placeholder?: string
}) {
  const id = useId()
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className={masquerLibelle ? "sr-only" : "text-[13px] font-semibold"}>
        {libelle}
      </label>
      <input
        id={id}
        type="text"
        value={valeur}
        autoFocus={autoFocus}
        required={required}
        placeholder={placeholder}
        onChange={(evenement) => onChange(evenement.target.value)}
        className="h-10 rounded-[12px] border-0 bg-card px-3 text-sm [box-shadow:inset_0_0_0_1px_var(--v-edge)]"
      />
    </div>
  )
}

export function ZoneTexte({
  libelle,
  valeur,
  onChange,
  lignes = 3,
  className,
}: {
  libelle: string
  valeur: string
  onChange: (valeur: string) => void
  lignes?: number
  className?: string
}) {
  const id = useId()
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[13px] font-semibold">
        {libelle}
      </label>
      <textarea
        id={id}
        rows={lignes}
        value={valeur}
        onChange={(evenement) => onChange(evenement.target.value)}
        className="resize-y rounded-[14px] border-0 bg-card px-3 py-2.5 text-sm leading-[1.45] [box-shadow:inset_0_0_0_1px_var(--v-edge)]"
      />
    </div>
  )
}
