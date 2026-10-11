"""Écriture d'un script d'épisode par Claude (API Anthropic).

À partir d'un sujet, Claude rédige un script.md au format attendu par le
pipeline (segments séparés par une ligne vide, directives [text:]/[source:],
narration lue par la voix). Nécessite le paquet `anthropic` et une clé API.
"""
from __future__ import annotations

import os
from typing import Any

DEFAULT_MODEL = "claude-opus-5-5"

_SYSTEM = """Tu écris le SCRIPT d'une courte vidéo pour une chaîne, en français.
Tu réponds UNIQUEMENT par le script, sans explication, sans blocs de code.

Format EXACT à respecter :
- La première ligne est le titre : « # Titre de la vidéo ».
- Ensuite, un SEGMENT par bloc, séparés par UNE LIGNE VIDE.
- Chaque segment commence par une directive de texte à l'écran :
    [text: titre court du segment]
- Puis 1 à 3 phrases de NARRATION (ce que la voix va lire), naturelles,
  claires, faites pour être dites à l'oral (pas de listes, pas de symboles).
- Tu peux ajouter une ligne [source: ...] si une source est pertinente.
- N'ajoute PAS de directive [img:] (les images seront choisies après).

Exemple de segment :
[text: Pourquoi c'est utile]
Voici la phrase que la voix va lire. Elle reste simple et directe.
"""


def generate_script(topic: str, n_segments: int, cfg: dict[str, Any],
                     api_key: str | None = None) -> str:
    """Renvoie le texte du script.md rédigé par Claude."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Le paquet 'anthropic' n'est pas installé.\n"
            "Installe-le :  pip install anthropic") from exc

    ai = cfg.get("ai") or {}
    key = api_key or os.environ.get("ANTHROPIC_API_KEY") or ai.get("key")
    if not key:
        raise RuntimeError(
            "Clé API Claude manquante. Renseigne-la dans l'appli "
            "(ou la variable ANTHROPIC_API_KEY).")
    model = ai.get("model") or DEFAULT_MODEL
    n = max(2, min(int(n_segments or 5), 20))

    prompt = (
        f"Sujet de la vidéo : {topic.strip()}\n\n"
        f"Écris le script avec exactement {n} segments (en plus du titre). "
        f"Garde une narration concise, adaptée à une voix off."
    )

    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # réseau, clé invalide, quota…
        raise RuntimeError(f"Appel à Claude échoué : {exc}") from exc

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    text = text.strip()
    # Garde-fou : retire d'éventuels blocs de code si le modèle en a mis.
    if text.startswith("```"):
        lines = [l for l in text.splitlines() if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    if not text:
        raise RuntimeError("Claude n'a renvoyé aucun texte.")
    if not text.lstrip().startswith("#"):
        text = f"# {topic.strip()[:60]}\n\n" + text
    return text + "\n"
