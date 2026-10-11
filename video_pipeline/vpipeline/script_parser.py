"""Analyse d'un script d'épisode -> liste de segments.

Format du script (fichier texte / markdown), un segment par bloc séparé par
une ligne vide :

    # Titre de l'épisode                <- optionnel, sert à l'intro

    [img: photo1.jpg]                   <- image du segment (optionnel)
    [text: Bienvenue sur la chaîne]     <- texte affiché à l'écran (optionnel)
    [source: OpenBuilds docs]           <- bandeau sources discret (optionnel)
    Voici la narration lue par la voix. <- tout le reste = texte lu (TTS)
    Elle peut tenir sur plusieurs lignes.

    [img: photo2.jpg]
    Deuxième segment...

Règles simples :
- Les lignes `[clé: valeur]` sont des directives ; tout le reste est narré.
- Si un segment n'indique pas d'image, on prend la suivante du dossier images/.
- Les lignes commençant par `#` ou `//` (hors directive) sont ignorées.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .util import die

_DIRECTIVE = re.compile(r"^\[(\w+)\s*:\s*(.*?)\]\s*$")
_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


@dataclass
class Segment:
    narration: str
    image: Path | None = None
    caption: str | None = None       # [text: ...]
    source: str | None = None        # [source: ...]
    extras: dict[str, str] = field(default_factory=dict)


@dataclass
class Episode:
    title: str
    segments: list[Segment]


def _list_images(images_dir: Path) -> list[Path]:
    if not images_dir.is_dir():
        return []
    return sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _IMG_EXT
    )


def parse_script(script_path: Path, images_dir: Path) -> Episode:
    if not script_path.exists():
        die(f"Script introuvable : {script_path}")

    raw = script_path.read_text(encoding="utf-8")
    pool = _list_images(images_dir)
    used: set[Path] = set()

    title = script_path.stem.replace("_", " ").title()
    segments: list[Segment] = []

    # Découpe en blocs séparés par au moins une ligne vide.
    blocks = re.split(r"\n\s*\n", raw.strip())
    for block in blocks:
        narration_lines: list[str] = []
        image: Path | None = None
        caption: str | None = None
        source: str | None = None
        extras: dict[str, str] = {}

        for line in block.splitlines():
            s = line.strip()
            if not s:
                continue
            m = _DIRECTIVE.match(s)
            if m:
                key, val = m.group(1).lower(), m.group(2).strip()
                if key in ("img", "image"):
                    image = _resolve_image(val, images_dir)
                elif key in ("text", "caption", "titre"):
                    caption = val
                elif key in ("source", "sources"):
                    source = val
                elif key == "title":
                    title = val
                else:
                    extras[key] = val
                continue
            if s.startswith("# "):
                # Un titre markdown hors directive définit le titre de l'épisode.
                title = s[2:].strip()
                continue
            if s.startswith("//"):
                continue
            narration_lines.append(s)

        narration = " ".join(narration_lines).strip()
        if not narration and image is None and caption is None:
            continue  # bloc vide (ex: juste le titre)

        if image is not None:
            used.add(image)
        segments.append(
            Segment(narration=narration, image=image, caption=caption,
                    source=source, extras=extras)
        )

    # Auto-attribution des images non référencées, dans l'ordre du dossier.
    remaining = [p for p in pool if p not in used]
    ri = 0
    for seg in segments:
        if seg.image is None and ri < len(remaining):
            seg.image = remaining[ri]
            ri += 1

    missing = [i for i, s in enumerate(segments) if s.image is None]
    if missing:
        die(
            f"{len(missing)} segment(s) sans image et plus d'image dispo dans "
            f"{images_dir}. Ajoute des images ou utilise [img: nom.jpg]."
        )
    if not segments:
        die("Le script ne contient aucun segment exploitable.")
    return Episode(title=title, segments=segments)


def _resolve_image(name: str, images_dir: Path) -> Path:
    cand = images_dir / name
    if cand.exists():
        return cand
    direct = Path(name)
    if direct.exists():
        return direct
    die(f"Image introuvable : {name!r} (cherchée dans {images_dir}).")
