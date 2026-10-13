"""Recherche d'images automatique, avec deux banques :

  - pixabay   : gratuit, nécessite une clé API, aucune attribution requise.
  - openverse : Creative Commons, AUCUNE clé requise (banque de secours) ;
                l'attribution de l'auteur est ajoutée au bandeau « Sources ».

Comportement : on interroge la banque choisie (provider), et si elle ne donne
rien (pas de clé, panne, aucun résultat), on bascule sur la banque de secours
(fallback). Ainsi la recherche d'images marche même sans clé Pixabay.

Clé Pixabay : variable d'environnement PIXABAY_API_KEY ou cfg["images"]["key"].
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

_UA = {"User-Agent": "GenerateurVideo/1.0 (+https://github.com/)"}

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
    base = caption or narration or ""
    words = re.findall(r"[^\W\d_]{3,}", caption if caption else narration,
                       flags=re.UNICODE)
    kept = [w for w in words if w.lower() not in _STOP][:max_words]
    return " ".join(kept) if kept else base[:40]


def _get_json(url: str) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log(f"  réseau: {exc}")
        return None


# --------------------------------------------------------------------------- #
# Banques d'images -> renvoient (url_image, attribution_ou_None)
# --------------------------------------------------------------------------- #
def _pixabay(query: str, cfg: dict[str, Any], api_key: str | None) -> tuple[str | None, str | None]:
    if not api_key:
        return None, None
    ic = cfg.get("images") or {}
    params = {
        "key": api_key, "q": query, "image_type": "photo",
        "safesearch": "true" if ic.get("safesearch", True) else "false",
        "per_page": "5", "lang": ic.get("lang", "fr"),
    }
    if ic.get("orientation") in ("horizontal", "vertical"):
        params["orientation"] = ic["orientation"]
    data = _get_json("https://pixabay.com/api/?" + urllib.parse.urlencode(params))
    hits = (data or {}).get("hits") or []
    if not hits:
        return None, None
    h = hits[0]
    return h.get("largeImageURL") or h.get("fullHDURL") or h.get("webformatURL"), None


def _openverse(query: str, cfg: dict[str, Any], api_key: str | None) -> tuple[str | None, str | None]:
    params = {
        "q": query, "page_size": "5",
        "license_type": "commercial",   # réutilisable, y compris commercial
        "mature": "false",
    }
    data = _get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params))
    results = (data or {}).get("results") or []
    if not results:
        return None, None
    r = results[0]
    url = r.get("url")
    creator = r.get("creator") or "auteur inconnu"
    lic = (r.get("license") or "").upper()
    ver = r.get("license_version") or ""
    attribution = f"{creator} / CC {lic} {ver}".strip() + " (Openverse)"
    return url, attribution


def _pollinations(query: str, cfg: dict[str, Any], api_key: str | None) -> tuple[str | None, str | None]:
    """Génère une image par IA (Pollinations) — GRATUIT, sans clé.
    On construit l'URL ; l'image est créée au moment du téléchargement."""
    ic = cfg.get("images") or {}
    w, h = (1280, 720) if ic.get("orientation") != "vertical" else (720, 1280)
    base = query.strip() or "illustration"
    # On enrichit un peu la demande pour un rendu propre et exploitable.
    full = f"{base}, illustration réaliste, haute qualité, éclairage cinématographique"
    prompt = urllib.parse.quote(full)
    url = (f"https://image.pollinations.ai/prompt/{prompt}"
           f"?width={w}&height={h}&nologo=true")
    return url, None


_PROVIDERS = {"pixabay": _pixabay, "openverse": _openverse, "ia": _pollinations}


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return dest.stat().st_size > 1000
    except Exception as exc:
        log(f"  téléchargement échoué ({exc})")
        return False


def _resolve_key(cfg: dict[str, Any]) -> str | None:
    return os.environ.get("PIXABAY_API_KEY") or (cfg.get("images") or {}).get("key")


def auto_fetch(episode: Episode, cfg: dict[str, Any], images_dir: Path) -> int:
    """Télécharge une image pour chaque segment sans image. Retourne le nombre
    d'images récupérées. Essaie la banque 'provider' puis, à défaut, 'fallback'."""
    needing = [(i, s) for i, s in enumerate(episode.segments) if s.image is None]
    if not needing:
        return 0

    ic = cfg.get("images") or {}
    provider = str(ic.get("provider", "pixabay")).lower()
    fallback = str(ic.get("fallback") or "").lower() or None
    pix_key = _resolve_key(cfg)

    # Ordre d'essai des banques (sans doublon), avec l'IA en DERNIER RECOURS :
    # Pollinations génère une image pour n'importe quel texte, donc aucun
    # segment ne reste jamais sans image.
    order: list[str] = []
    for p in (provider, fallback, "ia"):
        if p in _PROVIDERS and p not in order:
            order.append(p)
    if not order:
        order = ["openverse", "ia"]
    # Si Pixabay est demandé sans clé, on prévient mais on continue : il reste
    # toujours une banque sans clé (Openverse) et l'IA en dernier recours.
    if "pixabay" in order and not pix_key:
        log("Pixabay sans clé : bascule automatique sur les sources sans clé "
            "(Openverse, puis image générée par IA).")
        order = [p for p in order if p != "pixabay"]

    images_dir.mkdir(parents=True, exist_ok=True)
    got = 0
    for i, seg in needing:
        q = keywords(seg.caption, seg.narration)
        url = attribution = None
        used = ""
        for prov in order:
            url, attribution = _PROVIDERS[prov](q, cfg, pix_key)
            if url:
                used = prov
                break
        if not url:
            log(f"segment {i + 1} : aucune image trouvée pour « {q} »")
            continue
        dest = images_dir / f"auto_{i:02d}.jpg"
        log(f"segment {i + 1} : image « {q} » via {used}")
        if _download(url, dest):
            seg.image = dest
            got += 1
            # Openverse (CC) : on crédite l'auteur dans le bandeau Sources.
            if attribution and not seg.source:
                seg.source = attribution
    log(f"{got}/{len(needing)} image(s) récupérée(s) automatiquement.")
    return got
