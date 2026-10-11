"""Recherche d'images automatique via une banque d'images (Pixabay).

Pour chaque segment sans image, on extrait des mots-clés (le texte à l'écran
`[text:]` en priorité, sinon la narration), on interroge la banque et on
télécharge la meilleure image dans le dossier images/ de l'épisode.

Clé API : variable d'environnement PIXABAY_API_KEY, ou cfg["images"]["key"].
Pixabay est gratuit et n'impose aucune attribution.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .script_parser import Episode
from .util import die, log

# Petits mots français/anglais à ignorer dans les mots-clés.
_STOP = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "à", "au",
    "aux", "en", "dans", "sur", "sous", "pour", "par", "avec", "sans", "ce",
    "cet", "cette", "ces", "se", "sa", "son", "ses", "ton", "ta", "tes", "mon",
    "ma", "mes", "il", "elle", "ils", "elles", "on", "nous", "vous", "je", "tu",
    "que", "qui", "quoi", "dont", "où", "est", "sont", "être", "avoir", "fait",
    "plus", "moins", "très", "tout", "tous", "toute", "comme", "mais", "donc",
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with", "is",
    "are", "your", "you", "this", "that", "it",
}


def keywords(caption: str | None, narration: str, max_words: int = 5) -> str:
    """Construit une requête de mots-clés à partir du segment."""
    source = (caption or narration or "").strip()
    if caption:  # un [text:] est déjà court et pertinent
        words = re.findall(r"[^\W\d_]{3,}", caption, flags=re.UNICODE)
    else:
        words = re.findall(r"[^\W\d_]{3,}", narration, flags=re.UNICODE)
    kept = [w for w in words if w.lower() not in _STOP][:max_words]
    return " ".join(kept) if kept else source[:40]


def _resolve_key(cfg: dict[str, Any]) -> str:
    key = os.environ.get("PIXABAY_API_KEY") or (cfg.get("images") or {}).get("key")
    if not key:
        die("Recherche d'images : renseigne ta clé Pixabay "
            "(variable PIXABAY_API_KEY, champ dans l'appli, ou images.key).")
    return str(key)


def _pixabay_search(query: str, cfg: dict[str, Any], api_key: str) -> str | None:
    """Renvoie l'URL de la meilleure image, ou None."""
    img_cfg = cfg.get("images") or {}
    params = {
        "key": api_key,
        "q": query,
        "image_type": "photo",
        "safesearch": "true" if img_cfg.get("safesearch", True) else "false",
        "per_page": "5",
        "lang": img_cfg.get("lang", "fr"),
    }
    orient = img_cfg.get("orientation", "horizontal")
    if orient in ("horizontal", "vertical"):
        params["orientation"] = orient
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "GenerateurVideo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log(f"  Pixabay: erreur réseau ({exc})")
        return None
    hits = data.get("hits") or []
    if not hits:
        return None
    h = hits[0]
    return h.get("largeImageURL") or h.get("fullHDURL") or h.get("webformatURL")


def _download(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "GenerateurVideo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return dest.stat().st_size > 0
    except Exception as exc:
        log(f"  téléchargement échoué ({exc})")
        return False


def auto_fetch(episode: Episode, cfg: dict[str, Any], images_dir: Path) -> int:
    """Télécharge une image pour chaque segment sans image. Retourne le nombre
    d'images récupérées."""
    needing = [(i, s) for i, s in enumerate(episode.segments) if s.image is None]
    if not needing:
        return 0

    api_key = _resolve_key(cfg)
    images_dir.mkdir(parents=True, exist_ok=True)
    got = 0
    for i, seg in needing:
        q = keywords(seg.caption, seg.narration)
        log(f"recherche d'image {i + 1} : « {q} »")
        url = _pixabay_search(q, cfg, api_key)
        if not url:
            log(f"  aucune image trouvée pour « {q} »")
            continue
        dest = images_dir / f"auto_{i:02d}.jpg"
        if _download(url, dest):
            seg.image = dest
            got += 1
        # Pixabay n'exige pas d'attribution : on ne touche pas au bandeau sources.
    log(f"{got}/{len(needing)} image(s) récupérée(s) automatiquement.")
    return got
