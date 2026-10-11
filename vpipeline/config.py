"""Configuration du pipeline : valeurs par défaut + fusion avec un fichier
de config optionnel (JSON natif, YAML si PyYAML est installé).

Le principe : tout marche sans config. Le fichier de config ne sert qu'à
figer le STYLE DE LA CHAÎNE (logo, couleurs, police, intro, bandeau sources)
pour le réutiliser tel quel d'un épisode à l'autre.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .util import die, find_default_font

# Formats prêts à l'emploi (nom -> largeur x hauteur).
FORMATS: dict[str, tuple[int, int]] = {
    "long": (1920, 1080),   # YouTube paysage 16:9
    "short": (1080, 1920),  # Shorts / Reels / TikTok 9:16
    "square": (1080, 1080),
}

DEFAULTS: dict[str, Any] = {
    "fps": 30,
    "formats": ["long"],            # liste parmi FORMATS, ou "WxH"
    "motion": True,                 # léger zoom (effet Ken Burns) sur les images
    "transition": "crossfade",      # "crossfade" (fondu enchaîné) ou "fade"
    "fade_seconds": 0.5,            # durée du fondu / crossfade
    "still_seconds": 2.5,           # durée d'une image sans narration ([hold:] écrase)
    "background_color": "0x101418",  # fond quand l'image ne couvre pas
    "font": None,                   # chemin .ttf ; auto-détecté si None

    "tts": {
        "backend": "elevenlabs",    # elevenlabs | edge | piper | espeak | dummy
        "voice": "fr-FR-DeniseNeural",   # utilisé par edge-tts
        "rate": "+0%",              # edge-tts : ex "+10%", "-5%"
        "words_per_minute": 160,    # utilisé par le backend 'dummy'
        "elevenlabs_voice_id": "Rachel",     # nom ou ID de voix ElevenLabs
        "elevenlabs_model": "eleven_multilingual_v2",
    },

    # Recherche d'images automatique (banque Pixabay) pour les segments sans image
    "images": {
        "auto": False,              # True = cherche et télécharge les images manquantes
        "provider": "pixabay",
        "key": None,                # sinon variable d'env PIXABAY_API_KEY
        "lang": "fr",               # langue des mots-clés
        "orientation": "horizontal",  # horizontal | vertical | any
        "safesearch": True,
    },

    # Style constant de la chaîne
    "logo": {
        "path": None,               # PNG transparent conseillé
        "height": 90,               # px (sur un rendu 1080p)
        "margin": 40,
        "position": "top-right",    # top-right | top-left | bottom-right | bottom-left
    },
    "captions": {                   # texte à l'écran par segment ([text: ...])
        "enabled": True,
        "fontsize": 46,
        "color": "white",
        "box_opacity": 0.55,
        "max_chars_per_line": 42,
        "position": "bottom",       # bottom | top | center
    },
    "source_banner": {              # bandeau sources discret ([source: ...])
        "enabled": True,
        "fontsize": 28,
        "color": "0xDDDDDD",
        "box_opacity": 0.45,
    },
    "intro": {
        "enabled": True,
        "seconds": 3.0,
        "title": None,              # si None -> titre du script
        "subtitle": None,
        "background": "0x101418",   # couleur ou chemin image
        "fontsize": 72,
    },
    "music": {
        "path": None,               # musique de fond optionnelle
        "volume": 0.12,             # 0..1
        "fade_seconds": 1.5,
    },
    "audio": {
        "bitrate": "192k",
        "gap_seconds": 0.35,        # silence entre deux segments
    },
    "output": {
        "video_bitrate": None,      # ex "8M" ; None -> CRF
        "crf": 20,
        "preset": "medium",
    },
}


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            die(
                f"Config YAML ({path.name}) mais PyYAML n'est pas installé.\n"
                "  -> pip install pyyaml   (ou utilise un fichier .json)"
            )
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        die(f"La config {path} doit être un objet (clé: valeur).")
    return data


def load_config(path: str | Path | None) -> dict[str, Any]:
    """Charge la config effective (défauts + fichier) et complète la police."""
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        p = Path(path)
        if not p.exists():
            die(f"Fichier de config introuvable : {p}")
        cfg = _deep_merge(cfg, _load_file(p))
    if not cfg.get("font"):
        cfg["font"] = find_default_font()
    return cfg


def resolve_formats(cfg: dict[str, Any]) -> list[tuple[str, int, int]]:
    """Transforme cfg['formats'] en liste (nom, largeur, hauteur)."""
    out: list[tuple[str, int, int]] = []
    for item in cfg.get("formats", ["long"]):
        if item in FORMATS:
            w, h = FORMATS[item]
            out.append((item, w, h))
        elif isinstance(item, str) and "x" in item.lower():
            w_s, h_s = item.lower().split("x", 1)
            out.append((item, int(w_s), int(h_s)))
        else:
            die(f"Format inconnu : {item!r} (attendu: long/short/square ou '1280x720').")
    return out
