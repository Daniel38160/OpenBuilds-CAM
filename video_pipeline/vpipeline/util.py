"""Utilitaires : exécution ffmpeg/ffprobe, log, formats de temps."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def log(msg: str) -> None:
    print(f"[vpipeline] {msg}", flush=True)


def die(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"[vpipeline] ERREUR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def require_tool(name: str) -> str:
    """Retourne le chemin d'un exécutable requis, sinon stoppe avec un message clair."""
    path = shutil.which(name)
    if not path:
        die(f"'{name}' introuvable dans le PATH. Installe-le (ex: apt install ffmpeg).")
    return path


def run(cmd: list[str], *, quiet: bool = True) -> None:
    """Lance une commande et stoppe proprement en cas d'échec."""
    log("$ " + " ".join(str(c) for c in cmd))
    proc = subprocess.run(
        [str(c) for c in cmd],
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-25:]
        die("échec de la commande:\n" + "\n".join(tail))


def probe_duration(path: str | Path) -> float:
    """Durée (secondes) d'un fichier média via ffprobe."""
    ffprobe = require_tool("ffprobe")
    out = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        die(f"ffprobe a échoué sur {path}:\n{out.stderr.strip()}")
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        die(f"impossible de lire la durée de {path}")


def srt_timestamp(seconds: float) -> str:
    """Formate un temps en SRT : HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap_text(text: str, max_chars: int) -> str:
    """Retour à la ligne manuel (drawtext ne wrap pas tout seul)."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def find_default_font() -> str | None:
    """Trouve une police système raisonnable pour les textes à l'écran."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None
