import { useId, type ReactNode } from "react"

import { cn } from "@/lib/utils"

export function EnTetePage({ titre, sousTitre, actions }: { titre: string; sousTitre?: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex flex-col gap-0.5">
        <h1 className="m-0 font-cojeev-display text-[26px] font-bold">{titre}</h1>
        {sousTitre && <p className="m-0 text-[13px] text-[color:var(--v-text-3)]">{sousTitre}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </header>
  )
}

export function Carte({
  titre,
  actions,
  className,
  children,
}: {
  titre?: string
  actions?: ReactNode
  className?: string
  children: ReactNode
}) {
  const id = useId()
  return (
    <section
      aria-labelledby={titre ? id : undefined}
      className={cn("flex flex-col gap-3.5 rounded-[var(--r-card)] bg-card p-5 text-card-foreground", className)}
    >
      {(titre || actions) && (
        <div className="flex items-center justify-between gap-3">
          {titre && (
            <h2 id={id} className="m-0 font-cojeev-display text-[21px] font-bold">
              {titre}
            </h2>
          )}
          {actions}
        </div>
      )}
      {children}
    </section>
  )
}

export function Alerte({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="m-0 rounded-[12px] bg-[var(--status-danger-bg)] px-4 py-3 text-sm text-[color:var(--status-danger-ink)]"
    >
      {children}
    </p>
  )
}
