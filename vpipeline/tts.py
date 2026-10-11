"""Synthèse vocale (TTS), backends interchangeables.

Chaque backend produit un WAV normalisé (44,1 kHz mono) et renvoie sa durée.
On normalise toujours au même format pour que l'assemblage audio soit fiable.

Backends :
  - edge       : edge-tts (gratuit, bonne qualité, nécessite internet)
  - piper      : piper (neuronal, hors-ligne, nécessite un modèle .onnx)
  - elevenlabs : API ElevenLabs (clé ELEVENLABS_API_KEY, qualité top)
  - espeak     : espeak-ng (hors-ligne, robotique) — dépannage
  - dummy      : silence calibré sur le nombre de mots — tests/CI sans réseau
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
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
        "edge": _edge,
        "streamelements": _streamelements,
        "piper": _piper,
        "elevenlabs": _elevenlabs,
        "espeak": _espeak,
        "dummy": _dummy,
    }.get(backend)
    if fn is None:
        die(f"Backend TTS inconnu : {backend!r}")
    fn(text, out_wav, cfg)
    return probe_duration(out_wav)


def _windows(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    """Voix intégrée à Windows (SAPI) — 100% locale, sans clé, sans internet,
    impossible à bloquer. Choisit une voix française si une est installée."""
    import os
    if os.name != "nt":
        die("Le backend 'windows' n'existe que sous Windows. "
            "Utilise 'streamelements' (gratuit) ou 'dummy' (test).")
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


def _streamelements(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    """Voix française GRATUITE, sans clé (service StreamElements / Polly).
    Voix FR dispo : Mathieu (homme), Celine, Lea (femmes), Chantal (fr-CA)."""
    import urllib.error
    import urllib.parse
    import urllib.request

    voice = cfg["tts"].get("se_voice", "Mathieu")
    url = ("https://api.streamelements.com/kappa/v2/speech?"
           + urllib.parse.urlencode({"voice": voice, "text": text[:550]}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    tmp_mp3 = out_wav.with_suffix(".se.mp3")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            tmp_mp3.write_bytes(resp.read())
    except urllib.error.HTTPError as exc:
        die(f"Voix gratuite (StreamElements) HTTP {exc.code}. "
            f"Vérifie la voix '{voice}' (Mathieu/Celine/Lea) ou réessaie.")
    except Exception as exc:
        die(f"Voix gratuite (StreamElements) a échoué : {exc}")
    _to_wav(tmp_mp3, out_wav)
    tmp_mp3.unlink(missing_ok=True)


def _to_wav(src: Path, dst: Path) -> None:
    """Convertit n'importe quel audio vers le WAV normalisé cible."""
    ffmpeg = require_tool("ffmpeg")
    subprocess.run(
        [ffmpeg, "-y", "-i", str(src), "-ar", str(TARGET_RATE),
         "-ac", str(TARGET_CH), str(dst)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
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


def _espeak(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    exe = require_tool("espeak-ng") if _which("espeak-ng") else require_tool("espeak")
    tmp = out_wav.with_suffix(".espeak.wav")
    subprocess.run([exe, "-v", "fr", "-s", "150", "-w", str(tmp), text],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    _to_wav(tmp, out_wav)
    tmp.unlink(missing_ok=True)


def _edge(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    try:
        import edge_tts  # type: ignore
    except ImportError:
        die("edge-tts non installé.  ->  pip install edge-tts   "
            "(ou TTS backend 'dummy' pour tester sans réseau)")

    voice = cfg["tts"].get("voice", "fr-FR-DeniseNeural")
    rate = cfg["tts"].get("rate", "+0%")
    tmp_mp3 = out_wav.with_suffix(".edge.mp3")

    async def _go() -> None:
        comm = edge_tts.Communicate(text, voice=voice, rate=rate)
        await comm.save(str(tmp_mp3))

    try:
        asyncio.run(_go())
    except Exception as exc:  # réseau, voix invalide, etc.
        die(f"edge-tts a échoué ({exc}). Vérifie la connexion / la voix "
            f"'{voice}', ou passe au backend 'dummy'.")
    _to_wav(tmp_mp3, out_wav)
    tmp_mp3.unlink(missing_ok=True)


def _piper(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    exe = require_tool("piper")
    model = cfg["tts"].get("piper_model")
    if not model or not Path(model).exists():
        die("Backend 'piper' : renseigne tts.piper_model (chemin du .onnx).")
    tmp = out_wav.with_suffix(".piper.wav")
    proc = subprocess.run(
        [exe, "--model", str(model), "--output_file", str(tmp)],
        input=text, text=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        die(f"piper a échoué :\n{proc.stderr.strip()}")
    _to_wav(tmp, out_wav)
    tmp.unlink(missing_ok=True)


def list_elevenlabs_voices(api_key: str) -> list[dict[str, str]]:
    """Liste les voix du compte ElevenLabs : [{'name','voice_id','labels'}, …]."""
    import json as _json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": (api_key or "").strip(), "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")[:200]
        if exc.code == 401:
            raise RuntimeError("clé invalide ou sans droit « Voices » (401). "
                               "Utilise une clé complète, ou colle l'ID de la voix.")
        raise RuntimeError(f"HTTP {exc.code} — {body}")
    except Exception as exc:
        raise RuntimeError(f"réseau : {exc}")
    out: list[dict[str, str]] = []
    for v in data.get("voices", []):
        labels = v.get("labels") or {}
        desc = ", ".join(str(x) for x in labels.values()) if labels else ""
        out.append({"name": v.get("name", "?"),
                    "voice_id": v.get("voice_id", ""), "labels": desc})
    return out


def _resolve_elevenlabs_voice(api_key: str, voice: str) -> str:
    """Accepte un ID (renvoyé tel quel) ou un NOM (résolu via l'API).
    Si le nom est introuvable, prend automatiquement la 1re voix du compte
    (évite l'erreur 'voice_not_found')."""
    v = (voice or "").strip()
    # Un ID ElevenLabs est une chaîne ~20 caractères alphanumériques sans espace.
    if v and " " not in v and len(v) >= 18 and v.isalnum():
        return v
    try:
        voices = list_elevenlabs_voices(api_key)
        vl = v.lower()
        # 1) correspondance exacte du nom
        for entry in voices:
            if entry["name"].lower() == vl:
                return entry["voice_id"]
        # 2) correspondance partielle (ex: « Nelly » -> « Nelly - French ... »)
        if vl:
            for entry in voices:
                if vl in entry["name"].lower():
                    return entry["voice_id"]
        # 3) à défaut, la première voix du compte
        if voices:
            log(f"Voix ElevenLabs « {v or '(vide)'} » introuvable — "
                f"utilisation de « {voices[0]['name']} ».")
            return voices[0]["voice_id"]
    except Exception:
        pass
    return v or "21m00Tcm4TlvDq8ikWAM"  # ultime repli : ID de la voix « Rachel »


def _elevenlabs(text: str, out_wav: Path, cfg: dict[str, Any]) -> None:
    import urllib.error
    import urllib.request

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        die("Backend 'elevenlabs' : définis la variable ELEVENLABS_API_KEY.")
    voice_id = _resolve_elevenlabs_voice(api_key, cfg["tts"].get("elevenlabs_voice_id", "Rachel"))
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    import json as _json
    body = _json.dumps({
        "text": text,
        "model_id": cfg["tts"].get("elevenlabs_model", "eleven_multilingual_v2"),
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"},
    )
    tmp_mp3 = out_wav.with_suffix(".11l.mp3")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            tmp_mp3.write_bytes(resp.read())
    except urllib.error.HTTPError as exc:
        die(f"ElevenLabs HTTP {exc.code}: {exc.read().decode('utf-8', 'ignore')[:300]}")
    except Exception as exc:
        die(f"ElevenLabs a échoué : {exc}")
    _to_wav(tmp_mp3, out_wav)
    tmp_mp3.unlink(missing_ok=True)


def _which(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def preflight(cfg: dict[str, Any]) -> None:
    """Petit avertissement si un backend risque d'échouer silencieusement."""
    backend = cfg["tts"]["backend"].lower()
    if backend == "dummy":
        log("TTS = 'dummy' : la vidéo aura un son SILENCIEUX (mode test).")
