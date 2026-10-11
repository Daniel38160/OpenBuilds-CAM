"""Synthèse vocale (TTS) — version simple et fiable.

On ne garde que ce qui marche vraiment, sans clé et sans service en ligne
qui peut tomber :

  - windows  : voix intégrée à Windows (SAPI) — locale, sans clé, increvable.
  - fichier  : TU fournis un fichier audio (ta voix enregistrée, un mp3/wav).
               C'est géré dans assemble.py (le son est réparti sur les images).
  - dummy    : silence calibré sur le nombre de mots — pour tester sans son.

Chaque backend produit un WAV normalisé (44,1 kHz mono).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .util import die, log, probe_duration, require_tool

TARGET_RATE = 44100
TARGET_CH = 1


def synthesize(text: str, out_wav: Path, cfg: dict[str, Any]) -> float:
    """Génère out_wav pour `text` et renvoie sa durée en secondes."""
    backend = cfg["tts"]["backend"].lower()
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    text = text.strip() or "…"

    fn = {
        "windows": _windows,
        "dummy": _dummy,
    }.get(backend)
    if fn is None:
        die(f"Backend TTS inconnu : {backend!r} "
            "(choisis : windows, fichier ou dummy).")
    fn(text, out_wav, cfg)
    return probe_duration(out_wav)


def _windows(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    """Voix intégrée à Windows (SAPI) — 100% locale, sans clé, sans internet,
    impossible à bloquer. Choisit une voix française si une est installée."""
    if os.name != "nt":
        die("La voix 'windows' n'existe que sous Windows. "
            "Utilise 'fichier' (ta voix) ou 'dummy' (test silencieux).")
    tmp = out_wav.with_suffix(".sapi.wav")
    ps = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$fr=$s.GetInstalledVoices()|Where-Object {$_.VoiceInfo.Culture.Name -like 'fr*'}|Select-Object -First 1;"
        "if($fr){$s.SelectVoice($fr.VoiceInfo.Name)};"
        f"$s.SetOutputToWaveFile('{tmp}');"
        "$s.Speak([Console]::In.ReadToEnd());"
        "$s.Dispose()"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        input=text, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not tmp.exists():
        die("Voix Windows (SAPI) a échoué :\n" + (proc.stderr or "").strip()[-300:])
    _to_wav(tmp, out_wav)
    tmp.unlink(missing_ok=True)


def _dummy(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    """Silence dont la durée imite le débit de parole (hors-ligne)."""
    ffmpeg = require_tool("ffmpeg")
    wpm = max(60, int(cfg["tts"].get("words_per_minute", 160)))
    words = max(1, len(text.split()))
    dur = max(1.6, words / wpm * 60.0)
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi",
         "-i", f"anullsrc=r={TARGET_RATE}:cl=mono",
         "-t", f"{dur:.3f}", str(out_wav)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )


def _to_wav(src: Path, dst: Path) -> None:
    """Convertit n'importe quel audio vers le WAV normalisé cible."""
    ffmpeg = require_tool("ffmpeg")
    subprocess.run(
        [ffmpeg, "-y", "-i", str(src), "-ar", str(TARGET_RATE),
         "-ac", str(TARGET_CH), str(dst)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )


def preflight(cfg: dict[str, Any]) -> None:
    """Petit avertissement si un backend risque de surprendre."""
    backend = cfg["tts"]["backend"].lower()
    if backend == "dummy":
        log("Voix = 'dummy' : la vidéo aura un son SILENCIEUX (mode test).")
    elif backend == "fichier":
        vf = cfg["tts"].get("voice_file")
        if not vf:
            die("Voix = 'fichier' mais aucun fichier audio n'est indiqué.\n"
                "  -> choisis ton mp3/wav (bouton « Parcourir… ») "
                "ou passe à la voix 'windows'.")
        if not Path(vf).exists():
            die(f"Fichier audio introuvable : {vf}")
