import { useCallback, useState } from "react"

import { messageErreur } from "./requetes"

/** Exécute une action de l'API : occupation, erreur lisible, rechargement après réussite. */
export function useAction(recharger: () => void) {
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)

  const executer = useCallback(
    async (action: () => Promise<unknown>): Promise<boolean> => {
      setEnCours(true)
      try {
        await action()
        setErreur(null)
        recharger()
        return true
      } catch (e) {
        setErreur(messageErreur(e))
        return false
      } finally {
        setEnCours(false)
      }
    },
    [recharger],
  )

  return { erreur, enCours, executer }
}
