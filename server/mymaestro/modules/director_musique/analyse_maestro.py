"""Analyse audio de Maestro (librosa, demucs, faster-whisper) convertie vers l'analyse du Director (spec §6.1, D13).

Paroles fournies : elles font foi. Elles sont alignées sur les segments transcrits de façon optimale, dans l'ordre de la
chanson : des lignes consécutives peuvent se partager un segment, une ligne peut en couvrir plusieurs, et les segments
en trop (refrain répété mais écrit une fois, ad-libs) comme les lignes non transcrites restent libres. Sans paroles, les
segments transcrits deviennent les lignes, à relire à l'arrêt « après l'analyse ».
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from .modeles import Analyse, LigneParoles, Section

NOMS_SECTIONS = {
    "intro": "Intro", "verse": "Couplet", "chorus": "Refrain", "pre-chorus": "Pré-refrain", "prechorus": "Pré-refrain",
    "bridge": "Pont", "outro": "Outro", "instrumental": "Instrumental", "solo": "Solo",
}
ECART_VOIX_S = 1.5
SEUIL_RESSEMBLANCE = 0.3  # ressemblance minimale (mots) entre des lignes et les segments où on les cale
COUVERTURE_MIN = 0.5  # part minimale des mots de chaque ligne retrouvés dans ses segments : les mots-outils seuls ne suffisent pas
GROUPE_MAX = 4  # lignes chantées dans un même segment, ou segments couverts par une même ligne
LIGNE_MIN_MS = 100  # trou plus étroit que ça par ligne : ses lignes partagent le créneau de la ligne calée voisine

Segment = tuple[float, float, str]


def _nombre(valeur: Any, defaut: float = 0.0) -> float:
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return defaut


def _nom_section(label: Any) -> str:
    texte = str(label or "").strip()
    return NOMS_SECTIONS.get(texte.lower(), texte.capitalize() or "Section")


def _segments(brut: dict[str, Any]) -> list[Segment]:
    segments: list[Segment] = []
    for ligne in brut.get("lyrics") or []:
        if not isinstance(ligne, dict):
            continue
        debut, fin, texte = _nombre(ligne.get("start")), _nombre(ligne.get("end")), str(ligne.get("text") or "").strip()
        if round(fin, 3) > round(debut, 3) >= 0 and texte:
            segments.append((debut, fin, texte))
    return sorted(segments)


def _voix(segments: list[Segment]) -> list[Section]:
    blocs: list[list[float]] = []
    for debut, fin, _ in segments:
        if blocs and debut - blocs[-1][1] < ECART_VOIX_S:
            blocs[-1][1] = max(blocs[-1][1], fin)
        else:
            blocs.append([debut, fin])
    return [Section(nom="Voix", debut_s=round(debut, 3), fin_s=round(fin, 3)) for debut, fin in blocs]


def _mots(texte: str) -> list[str]:
    return re.findall(r"\w+", texte.lower())


def _couverture(ligne: list[str], mots: list[str]) -> float:
    """Part des mots de la ligne retrouvés, dans l'ordre, parmi `mots`."""
    if not ligne:
        return 0.0
    blocs = difflib.SequenceMatcher(None, ligne, mots, autojunk=False).get_matching_blocks()
    return sum(bloc.size for bloc in blocs) / len(ligne)


def _poids(lignes: list[list[str]], segments: list[list[str]]) -> float:
    """Poids d'un appariement de lignes consécutives avec des segments consécutifs : nombre de lignes × ressemblance de
    leurs mots mis bout à bout avec ceux des segments ; 0 s'il n'est pas crédible. Deux lignes identiques calées sur un
    seul segment pèsent donc moins que chacune sur le sien."""
    mots = [mot for segment in segments for mot in segment]
    if any(_couverture(ligne, mots) < COUVERTURE_MIN for ligne in lignes):
        return 0.0
    ressemblance = difflib.SequenceMatcher(None, [mot for ligne in lignes for mot in ligne], mots, autojunk=False).ratio()
    return len(lignes) * ressemblance if ressemblance >= SEUIL_RESSEMBLANCE else 0.0


def _aligner(lignes: list[list[str]], segments: list[list[str]], durees_ms: list[int]) -> list[tuple[int, int] | None]:
    """Plage de segments (premier, dernier) de chaque ligne, ou None. Programmation dynamique au poids total maximal ;
    à égalité, la ligne est calée plutôt que laissée libre, et sur la plage la plus tôt de la chanson."""
    n, m = len(lignes), len(segments)
    ensembles_segments = [set(segment) for segment in segments]
    communs = [[bool(set(ligne) & ensemble) for ensemble in ensembles_segments] for ligne in lignes]
    meilleur = [[0.0] * (m + 1) for _ in range(n + 1)]
    pas = [[(1, 0)] * (m + 1) for _ in range(n + 1)]  # (lignes consommées, segments consommés)
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            valeur, choisi = -1.0, (0, 1)
            appariements = [(k, 1) for k in range(1, min(GROUPE_MAX, n - i) + 1)]
            appariements += [(1, r) for r in range(2, min(GROUPE_MAX, m - j) + 1)]
            for k, r in appariements:
                if durees_ms[j] < k or not (all(communs[i + t][j] for t in range(k)) and communs[i][j + r - 1]):
                    continue
                poids = _poids(lignes[i:i + k], segments[j:j + r])
                if poids > 0 and poids + meilleur[i + k][j + r] > valeur + 1e-9:
                    valeur, choisi = poids + meilleur[i + k][j + r], (k, r)
            for k, r in ((0, 1), (1, 0)):  # segment libre, puis ligne libre
                if meilleur[i + k][j + r] > valeur + 1e-9:
                    valeur, choisi = meilleur[i + k][j + r], (k, r)
            meilleur[i][j], pas[i][j] = valeur, choisi
    plages: list[tuple[int, int] | None] = [None] * n
    i = j = 0
    while i < n and j < m:
        k, r = pas[i][j]
        if k and r:
            for t in range(k):
                plages[i + t] = (j, j + r - 1)
        i, j = i + k, j + r
    return plages


def _repartir(horaires: list[tuple[int, int] | None], membres: list[int], debut: int, fin: int) -> None:
    """Parts égales de [debut, fin] en millisecondes entières : le dernier membre finit exactement à `fin`."""
    for rang, membre in enumerate(membres):
        horaires[membre] = (debut + (fin - debut) * rang // len(membres), debut + (fin - debut) * (rang + 1) // len(membres))


def caler_paroles(textes: list[str], segments: list[Segment], duree_s: float = 0.0) -> list[LigneParoles]:
    """Cale chaque ligne sur la plage de segments transcrits qui lui correspond (alignement optimal sur les mots).

    Les lignes d'un même segment se le partagent à parts égales ; une ligne sur plusieurs segments va du début du
    premier à la fin du dernier. Les lignes non calées se répartissent à parts égales dans le trou entre la ligne calée
    précédente et la suivante (après la dernière, jusqu'à la fin de la chanson si elle est connue) ; un trou trop étroit
    est remplacé par le créneau de la ligne calée voisine, partagé avec elle. Calculs en millisecondes entières.
    """
    if not segments:
        return []
    debuts = [round(debut * 1000) for debut, _, _ in segments]
    fins = [round(fin * 1000) for _, fin, _ in segments]
    plages = _aligner([_mots(t) for t in textes], [_mots(s[2]) for s in segments], [f - d for d, f in zip(debuts, fins)])
    horaires: list[tuple[int, int] | None] = [None] * len(textes)
    for plage in sorted({p for p in plages if p is not None}):
        _repartir(horaires, [i for i, p in enumerate(plages) if p == plage], debuts[plage[0]], fins[plage[1]])
    fin_chanson = max(max(fins), round(duree_s * 1000))
    i = 0
    while i < len(textes):
        if horaires[i] is not None:
            i += 1
            continue
        j = i
        while j < len(textes) and horaires[j] is None:
            j += 1
        membres = list(range(i, j))
        debut = horaires[i - 1][1] if i > 0 else 0  # type: ignore[index]
        fin = horaires[j][0] if j < len(textes) else fin_chanson  # type: ignore[index]
        if fin - debut < LIGNE_MIN_MS * len(membres) and (i > 0 or j < len(textes)):  # trou vide ou trop étroit
            voisine = i - 1 if i > 0 else j
            membres = [voisine, *membres] if voisine < i else [*membres, voisine]
            debut, fin = horaires[voisine]  # type: ignore[misc]
        _repartir(horaires, membres, debut, fin)
        i = j
    # garde-fou pour une entrée dégénérée (créneau voisin de quelques millisecondes) : jamais de durée nulle
    return [LigneParoles(texte=t, debut_s=d / 1000, fin_s=max(f, d + 1) / 1000) for t, (d, f) in zip(textes, horaires)]  # type: ignore[misc]


def analyse_depuis_maestro(brut: dict[str, Any], paroles: str) -> Analyse:
    duree = _nombre(brut.get("duration"))
    temps_forts = sorted(
        round(_nombre(battement.get("time")), 3)
        for battement in brut.get("beats") or []
        if isinstance(battement, dict) and battement.get("time") is not None
    )
    sections = [
        Section(nom=_nom_section(s.get("label")), debut_s=round(max(0.0, _nombre(s.get("start"))), 3), fin_s=round(_nombre(s.get("end")), 3))
        for s in brut.get("sections") or []
        if isinstance(s, dict) and _nombre(s.get("end")) > max(0.0, _nombre(s.get("start")))
    ]
    segments = _segments(brut)
    textes = [ligne.strip() for ligne in paroles.splitlines() if ligne.strip()]
    if textes and segments:
        lignes = caler_paroles(textes, segments, duree)
    elif textes and duree > 0:  # transcription absente : réparties sur la chanson, à relire
        part = duree / len(textes)
        lignes = [LigneParoles(texte=t, debut_s=round(n * part, 3), fin_s=round((n + 1) * part, 3)) for n, t in enumerate(textes)]
    else:
        lignes = [LigneParoles(texte=t, debut_s=round(d, 3), fin_s=round(f, 3)) for d, f, t in segments]
    bpm = _nombre(brut.get("bpm"), 120.0)
    return Analyse(
        bpm=bpm if bpm > 0 else 120.0, temps_forts=temps_forts, sections=sections, voix=_voix(segments), lignes=lignes, simule=False
    )
