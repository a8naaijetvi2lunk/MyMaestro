import { useEffect, useState } from "react"

import { api, type EtatMoteurInstalle } from "@/api/client"
import { useDonnees, useRechargementSurEvenements } from "@/api/hooks"
import { exiger, executer, messageErreur } from "@/api/requetes"
import { Alerte, Carte, EnTetePage } from "@/components/commun/mise-en-page"
import { formatEspace } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  actionPossible,
  EVENEMENTS_MOTEURS,
  libelleEtape,
  libelleEtat,
  nomAccessibleAction,
  type ActionMoteur,
} from "@/lib/moteurs"

const LIBELLES_ACTION: Record<Exclude<ActionMoteur, "connecter">, string> = {
  installer: "Installer",
  reessayer: "Réessayer",
  reinstaller: "Réinstaller",
}

const LIBELLES_SOURCE: Record<string, string> = {
  "nvidia-smi": "nvidia-smi",
  config: "configuration",
  repli: "carte de référence par défaut",
}

export function PageMoteurs() {
  const { donnees: etat, erreur, recharger } = useDonnees("moteurs", () => exiger(api.GET("/api/moteurs")))
  useRechargementSurEvenements(recharger, 400, EVENEMENTS_MOTEURS)
  const { donnees: materiel } = useDonnees("materiel", () => exiger(api.GET("/api/materiel")))
  // La connexion à Claude se termine dans un terminal, hors de l'application : on relit l'état au retour sur l'onglet.
  useEffect(() => {
    const auRetour = () => {
      if (document.visibilityState === "visible") recharger()
    }
    document.addEventListener("visibilitychange", auRetour)
    window.addEventListener("focus", auRetour)
    return () => {
      document.removeEventListener("visibilitychange", auRetour)
      window.removeEventListener("focus", auRetour)
    }
  }, [recharger])
  const [erreurAction, setErreurAction] = useState<string | null>(null)
  const [actionEnCours, setActionEnCours] = useState<string | null>(null)

  if (erreur && !etat) return <Alerte>{erreur}</Alerte>
  if (!etat) return <p className="text-[color:var(--v-text-3)]">Chargement…</p>

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

  const installer = (moteur: EtatMoteurInstalle) =>
    agir(moteur.id, () =>
      executer(api.POST("/api/moteurs/{moteur_id}/installer", { params: { path: { moteur_id: moteur.id } } })),
    )

  return (
    <div className="flex flex-col gap-4">
      <EnTetePage
        titre="Moteurs"
        sousTitre="Les moteurs d'IA que MyMaestro pilote : détectés ici, téléchargés à une version épinglée et installés dans le dossier moteurs/."
      />
      {etat.mode_demo && (
        <p className="m-0 rounded-[12px] bg-[var(--v-yellow-soft)] px-4 py-3 text-sm">
          Mode démo (<code>MYMAESTRO_MOTEURS_REELS=aucun</code>) : les moteurs d'IA sont simulés, rien n'est bloqué.
        </p>
      )}
      {etat.redemarrage_requis && (
        <p className="m-0 rounded-[12px] bg-[var(--v-olive-soft)] px-4 py-3 text-sm">
          Un moteur vient d'être installé : redémarrez MyMaestro pour qu'il soit piloté.
        </p>
      )}
      {erreurAction && <Alerte>{erreurAction}</Alerte>}
      {materiel && (
        <Carte titre="Carte graphique">
          <div className="flex flex-col gap-1 text-[13px]">
            <strong>{materiel.gpu ?? "Carte NVIDIA non détectée"}</strong>
            <span className="text-[color:var(--v-text-3)]">
              VRAM : {materiel.vram_go.toFixed(1).replace(".", ",")} Go · source : {LIBELLES_SOURCE[materiel.source] ?? materiel.source}
            </span>
          </div>
          {materiel.avertissement && <Alerte>{materiel.avertissement}</Alerte>}
        </Carte>
      )}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        {etat.moteurs.map((moteur) => {
          const action = actionPossible(moteur)
          const enCours = moteur.etat === "en_cours"
          const incomplet = !enCours && moteur.etat === "incomplet"
          const messageEchec = !enCours && (incomplet || moteur.etat === "absent") ? moteur.message : null
          const journal = incomplet ? moteur.journal : null
          const determinee = moteur.progression !== null && moteur.progression !== undefined
          const part = Math.round((moteur.progression ?? 0) * 100)
          const nomEtape = moteur.etape ? libelleEtape(moteur.etape) : "Installation"
          return (
            <Carte
              key={moteur.id}
              titre={moteur.libelle}
              actions={
                <Badge variant={moteur.requis ? "pink-soft" : "dashed"}>{moteur.requis ? "requis" : "optionnel"}</Badge>
              }
            >
              <div className="flex flex-col gap-1 text-[13px]">
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={
                      moteur.etat === "installe" || moteur.etat === "externe"
                        ? "size-2.5 rounded-full bg-[var(--v-olive)]"
                        : enCours
                          ? "size-2.5 rounded-full bg-[var(--v-yellow)]"
                          : "size-2.5 rounded-full bg-[var(--v-border)]"
                    }
                  />
                  <strong>{libelleEtat(moteur.etat)}</strong>
                  {moteur.id === "claude" && (moteur.etat === "installe" || moteur.etat === "externe") && (
                    <span className="text-[color:var(--v-text-3)]">{moteur.connecte ? "· connecté" : "· non connecté"}</span>
                  )}
                </span>
                <span className="text-[color:var(--v-text-3)]">Version attendue : {moteur.version_attendue}</span>
                <span className="text-[color:var(--v-text-3)]">Espace nécessaire : {formatEspace(moteur.espace_mo)}</span>
                {moteur.note && <span className="text-[color:var(--v-text-2)]">{moteur.note}</span>}
              </div>
              {enCours && (
                <div className="flex flex-col gap-1.5">
                  <span
                    role="progressbar"
                    aria-label={`Progression de l'installation de ${moteur.libelle}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={determinee ? part : undefined}
                    aria-valuetext={determinee ? undefined : `${nomEtape} en cours`}
                    className="block h-2 rounded-full bg-[var(--v-beige)]"
                  >
                    {/* Progression inconnue : piste pleine atténuée, sans pourcentage inventé */}
                    <span
                      className={`block h-2 rounded-full bg-[var(--v-ink)]${determinee ? "" : " opacity-30"}`}
                      style={{ width: determinee ? `${part}%` : "100%" }}
                    />
                  </span>
                  <span className="text-xs text-[color:var(--v-text-3)]">
                    {[moteur.etape ? libelleEtape(moteur.etape) : null, moteur.message].filter(Boolean).join(" · ") || "Préparation…"}
                  </span>
                </div>
              )}
              {(messageEchec || journal) && (
                <div className="flex flex-col gap-1.5">
                  {messageEchec && <Alerte>{messageEchec}</Alerte>}
                  {journal && <span className="break-all text-xs text-[color:var(--v-text-3)]">Journal : {journal}</span>}
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {enCours && (
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={nomAccessibleAction("annuler", moteur.libelle)}
                    disabled={actionEnCours !== null}
                    onClick={() => void agir("annuler", () => executer(api.POST("/api/moteurs/annuler")))}
                  >
                    Annuler
                  </Button>
                )}
                {action === "connecter" ? (
                  <Button
                    size="sm"
                    aria-label={nomAccessibleAction("connecter", moteur.libelle)}
                    disabled={actionEnCours !== null}
                    onClick={() => void agir("connecter", () => executer(api.POST("/api/moteurs/claude/connecter")))}
                  >
                    Se connecter
                  </Button>
                ) : (
                  action && (
                    <Button
                      size="sm"
                      aria-label={nomAccessibleAction(action, moteur.libelle)}
                      disabled={actionEnCours !== null || etat.en_cours !== null}
                      onClick={() => void installer(moteur)}
                    >
                      {LIBELLES_ACTION[action]}
                    </Button>
                  )
                )}
              </div>
            </Carte>
          )
        })}
      </div>
    </div>
  )
}
