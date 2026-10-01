import subprocess
import sys

import pytest

from mymaestro.outils import controle, ffmpeg, systeme


def _ffmpeg_disponible() -> bool:
    try:
        ffmpeg.trouver("ffmpeg")
        ffmpeg.trouver("ffprobe")
        return True
    except FileNotFoundError:
        return False


def test_marge_de_memoire_engagee():
    go = 1024**3
    systeme.exiger_marge(55, lecteur=lambda: systeme.MemoireEngagee(128 * go, 83 * go))
    with pytest.raises(systeme.MemoireInsuffisante, match="fichier d'échange"):
        systeme.exiger_marge(55, lecteur=lambda: systeme.MemoireEngagee(86 * go, 41 * go))
    systeme.exiger_marge(55, lecteur=lambda: None)  # hors Windows : pas de contrôle


@pytest.mark.skipif(sys.platform != "win32", reason="Windows seulement")
def test_lecture_de_la_memoire_engagee():
    etat = systeme.memoire_engagee()
    assert etat is not None and 0 < etat.disponible_octets <= etat.limite_octets


def test_repere_un_maestro_lance_a_la_main():
    texte = (
        "4120\t\\outils\\python.exe\t\\outils\\python.exe -u launch.py\t\\outils\\Maestro\\app\\env\\Scripts\\python.exe\n"
        "5000\t\\Python\\python.exe\tpython -m pytest\t\n"
        "6100\t\\outils\\Maestro\\app\\env\\Scripts\\python.exe\t\"\\outils\\Maestro\\app\\env\\Scripts\\python.exe\" launch.py\t\n"
    )
    assert systeme.lignes_processus_maestro(texte, r"\outils\Maestro\app") == [4120, 6100]


def _video(chemin, images, couleur):
    subprocess.run(
        [ffmpeg.trouver("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={couleur}:s=64x36:r=24",
         "-frames:v", str(images), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(chemin)],
        check=True, capture_output=True, timeout=60,
    )
    return chemin


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_controle_des_sorties(tmp_path):
    bonne = _video(tmp_path / "bonne.mp4", 48, "0x95BAE8")
    verdict = controle.controler_video(bonne, 48)
    assert verdict.valide and verdict.images == 48 and verdict.luminance > 50
    assert controle.controler_video(bonne, 49).valide  # une image de moins tolérée
    tronquee = controle.controler_video(bonne, 60)
    assert not tronquee.valide and "tronquée" in tronquee.motif
    noire = controle.controler_video(_video(tmp_path / "noire.mp4", 24, "black"), 24)
    assert not noire.valide and "noire" in noire.motif
    (tmp_path / "vide.mp4").write_bytes(b"pas une video")
    assert not controle.controler_video(tmp_path / "vide.mp4", 24).valide
