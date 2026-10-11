#!/usr/bin/env python3
"""Vérifie que tout le nécessaire est présent pour générer des vidéos.

Utilisable :
  - en ligne de commande :  python check_setup.py   (affiche un rapport ✓/✗)
  - depuis l'appli : elle appelle run_checks() au démarrage pour afficher un bilan.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _ffmpeg_ready() -> bool:
    """ffmpeg trouvable (y compris un ffmpeg embarqué dans bin/)."""
    try:
        import gui  # réutilise la détection d'un ffmpeg embarqué
        gui.bootstrap_ffmpeg()
    except Exception:
        pass
    return shutil.which("ffmpeg") is not None


def _version(tool: str) -> str:
    try:
        out = subprocess.run([tool, "-version"], capture_output=True, text=True)
        return out.stdout.splitlines()[0] if out.stdout else tool
    except Exception:
        return tool


def run_checks() -> list[tuple[str, bool, str]]:
    """Renvoie une liste (libellé, ok, conseil_si_ko)."""
    checks: list[tuple[str, bool, str]] = []

    # Python
    v = sys.version_info
    checks.append((f"Python {v.major}.{v.minor}.{v.micro}", True, ""))

    # ffmpeg / ffprobe (essentiels)
    ff = _ffmpeg_ready()
    checks.append(("ffmpeg (moteur vidéo)", ff,
                   "" if ff else "Installe-le : winget install Gyan.FFmpeg, "
                   "puis rouvre la fenêtre. (ou place ffmpeg.exe dans bin/)"))
    fp = shutil.which("ffprobe") is not None
    checks.append(("ffprobe (mesure des durées)", fp,
                   "" if fp else "Fourni avec ffmpeg : voir la ligne ci-dessus."))

    # tkinter (interface)
    tk_ok = importlib.util.find_spec("tkinter") is not None
    checks.append(("tkinter (fenêtre de l'appli)", tk_ok,
                   "" if tk_ok else "Réinstalle Python en incluant « tcl/tk »."))

    # Fichiers de l'appli (dans l'exe, ils sont embarqués -> on teste l'import)
    if getattr(sys, "frozen", False):
        files_ok = importlib.util.find_spec("vpipeline") is not None
    else:
        files_ok = (HERE / "gui.py").exists() and (HERE / "vpipeline").is_dir()
    checks.append(("Fichiers de l'appli", files_ok,
                   "" if files_ok else "Lance ce script depuis le dossier du projet."))

    # edge-tts (optionnel : seulement pour la voix gratuite 'edge')
    edge_ok = importlib.util.find_spec("edge_tts") is not None
    checks.append(("edge-tts (voix gratuite, optionnel)", edge_ok,
                   "" if edge_ok else "Optionnel : pip install edge-tts "
                   "(pas nécessaire pour ElevenLabs ou dummy)."))

    return checks


ESSENTIAL = {"ffmpeg (moteur vidéo)", "ffprobe (mesure des durées)",
             "tkinter (fenêtre de l'appli)", "Fichiers de l'appli"}


def all_essentials_ok(checks: list[tuple[str, bool, str]]) -> bool:
    return all(ok for label, ok, _ in checks if label in ESSENTIAL)


def main() -> int:
    print("=== Vérification de l'installation — Générateur de vidéo ===\n")
    checks = run_checks()
    for label, ok, hint in checks:
        print(f"  [{'OK' if ok else '  '}] {'✓' if ok else '✗'}  {label}")
        if not ok and hint:
            print(f"         -> {hint}")
    ok = all_essentials_ok(checks)
    print("\n" + ("Tout est prêt : tu peux générer des vidéos." if ok else
                  "Il manque un élément essentiel (voir les ✗ ci-dessus)."))
    if _ffmpeg_ready():
        print("ffmpeg : " + _version("ffmpeg"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
