import { useState } from "react"

import { api, type EtatConnecteur, type Job } from "@/api/client"
import { useEtatFile } from "@/api/hooks"
import { exiger, messageErreur } from "@/api/requetes"
import { Alerte, Carte, EnTetePage } from "@/components/commun/mise-en-page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { departFile, formatGo, grouperParMoteur, ordonnerCommeArbitre, vramTenue } from "@/lib/file"
import { libelleConnecteur, libelleModele, libellePhase } from "@/lib/format"
import { cn } from "@/lib/utils"

const DETAILS_CONNECTEUR: Record<string, string> = {
  maestro: ":7870 · Qwen, H3, LTX, FlashVSR, MMAudio",
  dlss5: "Python 3.13 embarqué · script sans interface",
  bonsai: "exige l'arrêt complet de Maestro",
  claude: "cloud, abonnement",
  export: "ffmpeg local · hors GPU, en parallèle de la file",
}

const ETATS_MOTEUR: Record<EtatConnecteur["etat"], { libelle: string; pastille: string }> = {
  charge: { libelle: "chargé", pastille: "bg-[var(--v-yellow)]" },
  demarre: { libelle: "démarré", pastille: "bg-[var(--v-olive)]" },
  arrete: { libelle: "arrêté", pastille: "bg-[var(--v-border)]" },
}

const STATUTS_JOB: Record<Job["statut"], string> = {
  en_file: "en file",
  en_cours: "en cours",
  termine: "terminé",
  echec: "échec",
  annule: "annulé",
}

function libelleJob(job: Job): string {
  return job.libelle || `${libelleConnecteur(job.connecteur)} · ${libelleModele(job.modele)}`
}

export function PageFile() {
  const { donnees: etat, erreur, recharger } = useEtatFile()
  const [erreurAction, setErreurAction] = useState<string | null>(null)
  const [actionEnCours, setActionEnCours] = useState<string | null>(null)

  if (erreur && !etat) return <Alerte>{erreur}</Alerte>
  if (!etat) return <p className="text-[color:var(--v-text-3)]">Chargement…</p>

  const gpu = etat.jobs.filter((j) => j.voie === "gpu")
  const enCours = gpu.find((j) => j.statut === "en_cours") ?? null
  const depart = departFile(etat.jobs, etat.connecteurs)
  const aSuivre = grouperParMoteur(ordonnerCommeArbitre(gpu.filter((j) => j.statut === "en_file"), depart))
  const echecs = etat.jobs.filter((j) => j.voie === "gpu" && j.statut === "echec")
  const cloud = etat.jobs.filter((j) => j.voie === "cloud" && j.statut !== "annule")
  const tete = enCours ?? gpu.find((j) => j.statut === "en_file") ?? null
  const regime = tete
    ? tete.regime === "carte"
      ? "Régime : à la carte"
      : `Régime : par phases${tete.phase ? ` — ${libellePhase(tete.phase)}` : ""}`
    : "File vide"
  const compte = (statut: Job["statut"]) => etat.jobs.filter((j) => j.statut === statut).length
  const tenue = vramTenue(etat.connecteurs)
  const part = etat.vram_totale_mo ? Math.min(100, Math.round((tenue / etat.vram_totale_mo) * 100)) : 0

  async function agir(cle: string, requete: () => Promise<unknown>) {
    if (actionEnCours) return
    setActionEnCours(cle)
    try {
      await requete()
      setErreurAction(null)
      recharger()
    } catch (e) {
      setErreurAction(messageErreur(e))
    } finally {
      setActionEnCours(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <EnTetePage
        titre="File GPU"
        sousTitre="Un seul GPU : un moteur chargé à la fois. Les jobs sont regroupés par moteur pour limiter les chargements."
        actions={
          <>
            <Badge variant="yellow-soft">{regime}</Badge>
            <Button
              variant="outline"
              disabled={actionEnCours !== null}
              onClick={() =>
                void agir("pause", () => exiger(etat.en_marche ? api.POST("/api/file/pause") : api.POST("/api/file/reprendre")))
              }
            >
              {etat.en_marche ? "Mettre en pause" : "Reprendre"}
            </Button>
          </>
        }
      />
      {erreurAction && <Alerte>{erreurAction}</Alerte>}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,700px)_minmax(0,1fr)]">
        <Carte titre="Voie GPU · un job à la fois">
          {enCours ? (
            <div className="flex flex-col gap-2 rounded-2xl bg-[var(--v-yellow-soft)] p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-bold">{libelleJob(enCours)}</span>
                <Badge variant="yellow">En cours · {Math.round(enCours.progression * 100)} %</Badge>
              </div>
              <span className="text-[13px] text-[color:var(--v-text-2)]">
                {libelleConnecteur(enCours.connecteur)} · {libelleModele(enCours.modele)}
              </span>
              <span className="block h-2 rounded-full bg-card">
                <span
                  className="block h-2 rounded-full bg-[var(--v-yellow-deep)]"
                  style={{ width: `${Math.round(enCours.progression * 100)}%` }}
                />
              </span>
            </div>
          ) : (
            <p className="m-0 text-sm text-[color:var(--v-text-3)]">Aucun job GPU en cours.</p>
          )}
          <SousTitre>À suivre, groupé par moteur</SousTitre>
          {aSuivre.length === 0 ? (
            <p className="m-0 text-sm text-[color:var(--v-text-3)]">Rien en attente.</p>
          ) : (
            <ol className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]">
              {aSuivre.map((groupe, indice) => (
                <li
                  key={`${groupe.cle}-${indice}`}
                  className="flex items-center justify-between gap-3 rounded-[12px] bg-[var(--v-beige-2)] px-3.5 py-2.5"
                >
                  <span>
                    <strong>{libelleModele(groupe.modele)}</strong> · {groupe.jobs.length} job{groupe.jobs.length > 1 ? "s" : ""}
                    {groupe.jobs[0].libelle && ` · ${groupe.jobs.map((j) => j.libelle).join(", ")}`}
                  </span>
                  <span className="text-[color:var(--v-text-3)]">{libelleConnecteur(groupe.connecteur)}</span>
                </li>
              ))}
            </ol>
          )}
          {echecs.length > 0 && (
            <>
              <SousTitre>Échecs</SousTitre>
              {echecs.map((job) => (
                <div
                  key={job.id}
                  className="flex flex-col gap-2.5 rounded-2xl bg-[var(--status-danger-bg)] p-4 [box-shadow:inset_0_0_0_1px_var(--v-danger)]"
                >
                  <div className="flex items-center justify-between gap-2 text-[color:var(--v-danger-ink)]">
                    <span className="text-sm font-bold">{libelleJob(job)}</span>
                    <span className="text-xs">
                      {job.tentatives} tentative{job.tentatives > 1 ? "s" : ""}
                    </span>
                  </div>
                  {job.erreur && <span className="text-[13px]">{job.erreur}</span>}
                  <div>
                    <Button
                      size="sm"
                      disabled={actionEnCours !== null}
                      onClick={() =>
                        void agir(job.id, () =>
                          exiger(api.POST("/api/file/jobs/{job_id}/relancer", { params: { path: { job_id: job.id } } })),
                        )
                      }
                    >
                      Relancer
                    </Button>
                  </div>
                </div>
              ))}
            </>
          )}
        </Carte>
        <div className="flex flex-col gap-4">
          <Carte titre="Moteurs">
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between text-xs text-[color:var(--v-text-3)]">
                <span>VRAM tenue (empreintes mesurées ou prudentes)</span>
                <span>
                  {formatGo(tenue)} / {formatGo(etat.vram_totale_mo)} Go
                </span>
              </div>
              <span className="block h-2 rounded-full bg-[var(--v-beige)]">
                <span className="block h-2 rounded-full bg-[var(--v-ink)]" style={{ width: `${part}%` }} />
              </span>
            </div>
            <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[13px]">
              {etat.connecteurs.map((c) => (
                <li key={c.nom} className="flex items-center gap-2.5">
                  <span aria-hidden="true" className={cn("size-2.5 shrink-0 rounded-full", ETATS_MOTEUR[c.etat].pastille)} />
                  <span className="flex-1">
                    <strong>{libelleConnecteur(c.nom)}</strong> · {DETAILS_CONNECTEUR[c.nom] ?? c.voie}
                  </span>
                  {c.simule && <Badge variant="dashed">simulé</Badge>}
                  <span className={c.etat === "arrete" ? "text-[color:var(--v-text-3)]" : "font-semibold"}>{ETATS_MOTEUR[c.etat].libelle}</span>
                </li>
              ))}
            </ul>
          </Carte>
          <Carte titre="Voie cloud · en parallèle">
            {cloud.length === 0 ? (
              <p className="m-0 text-sm text-[color:var(--v-text-3)]">Aucun job cloud.</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]">
                {cloud.map((job) => (
                  <li key={job.id} className="flex justify-between gap-3 rounded-[12px] bg-[var(--v-beige-2)] px-3.5 py-2.5">
                    <span>{libelleJob(job)}</span>
                    <span className={job.statut === "termine" ? "font-semibold text-[color:var(--v-olive-ink)]" : ""}>
                      {STATUTS_JOB[job.statut]}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Carte>
          <Carte titre="Bilan de la file">
            <p className="m-0 text-[13px] text-[color:var(--v-text-2)]">
              {compte("termine")} terminé{compte("termine") > 1 ? "s" : ""} · {compte("echec")} échec
              {compte("echec") > 1 ? "s" : ""} · {compte("en_file")} en file · {compte("annule")} annulé
              {compte("annule") > 1 ? "s" : ""}
            </p>
            <p className="m-0 text-xs text-[color:var(--v-text-3)]">
              À la fin de la phase vidéo d'un projet, un rapport est écrit et Windows envoie une notification.
            </p>
          </Carte>
        </div>
      </div>
    </div>
  )
}

function SousTitre({ children }: { children: string }) {
  return <span className="text-xs font-semibold uppercase tracking-[.06em] text-[color:var(--v-text-3)]">{children}</span>
}
