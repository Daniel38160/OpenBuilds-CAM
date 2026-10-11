"""Écriture d'un script d'épisode par une IA, au format attendu par le pipeline.

Deux fournisseurs :
  - groq   : GRATUIT et rapide (modèles Llama). Clé gratuite sur console.groq.com.
             Appel REST simple (aucune dépendance en plus de la stdlib).
  - claude : API Anthropic (payante). Nécessite le paquet `anthropic`.

Clé : passée par l'appli, ou variable d'env GROQ_API_KEY / ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "claude": "claude-opus-5-5",
}

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


def _prompts(topic: str, n: int) -> tuple[str, str]:
    user = (f"Sujet de la vidéo : {topic.strip()}\n\n"
            f"Écris le script avec exactement {n} segments (en plus du titre). "
            f"Garde une narration concise, adaptée à une voix off.")
    return _SYSTEM, user


def _clean(text: str, topic: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.splitlines()
                         if not l.strip().startswith("```")).strip()
    if not text:
        raise RuntimeError("L'IA n'a renvoyé aucun texte.")
    if not text.lstrip().startswith("#"):
        text = f"# {topic.strip()[:60]}\n\n" + text
    return text + "\n"


def _resolve(cfg: dict[str, Any], key_override: str | None) -> tuple[str, str, str]:
    """Renvoie (provider, model, key) ou lève une erreur claire."""
    ai = cfg.get("ai") or {}
    provider = (ai.get("provider") or "groq").lower()
    model = ai.get("model") or DEFAULT_MODELS.get(provider)
    if provider == "groq":
        key = key_override or os.environ.get("GROQ_API_KEY") or ai.get("key")
        if not key:
            raise RuntimeError("Clé Groq manquante (gratuite sur console.groq.com).")
    elif provider == "claude":
        key = key_override or os.environ.get("ANTHROPIC_API_KEY") or ai.get("key")
        if not key:
            raise RuntimeError("Clé Claude manquante (console.anthropic.com).")
    else:
        raise RuntimeError(f"Fournisseur IA inconnu : {provider}")
    return provider, model, key


def complete(messages: list[dict[str, str]], cfg: dict[str, Any],
             key_override: str | None = None, system: str = _SYSTEM) -> str:
    """Renvoie le texte produit par l'IA pour une conversation (liste de
    messages {role, content}). Garde le format de script via `system`."""
    provider, model, key = _resolve(cfg, key_override)
    if provider == "groq":
        return _groq(system, messages, model, key)
    return _claude(system, messages, model, key)


def clean_script(text: str, topic: str = "") -> str:
    """Nettoie un texte de script (retire les blocs de code, assure un titre)."""
    return _clean(text, topic)


def generate_script(topic: str, n_segments: int, cfg: dict[str, Any],
                    key_override: str | None = None) -> str:
    """Première rédaction d'un script à partir d'un sujet."""
    n = max(2, min(int(n_segments or 5), 20))
    _, user = _prompts(topic, n)
    text = complete([{"role": "user", "content": user}], cfg, key_override)
    return _clean(text, topic)


def _groq(system: str, messages: list[dict[str, str]], model: str, key: str) -> str:
    """Appel REST à l'API Groq (compatible OpenAI), via urllib."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": 0.7,
        "max_tokens": 2000,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Appel à Groq échoué : {exc}") from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Réponse Groq inattendue : {str(data)[:200]}")


def _claude(system: str, messages: list[dict[str, str]], model: str, key: str) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("Le paquet 'anthropic' n'est pas installé "
                           "(pip install anthropic), ou utilise Groq (gratuit).") from exc
    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model=model, max_tokens=16000, system=system, messages=messages,
        )
    except Exception as exc:
        raise RuntimeError(f"Appel à Claude échoué : {exc}") from exc
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
