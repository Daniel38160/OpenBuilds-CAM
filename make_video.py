#!/usr/bin/env python3
"""make_video — transforme un dossier d'épisode en vidéo.

Usage de base :
    python make_video.py episodes/demo

Un épisode = un dossier contenant :
    script.md        le texte (narration + directives [img:]/[text:]/[source:])
    images/          les images utilisées par les segments
    (config.yaml)    optionnel : surcharge le style par défaut de la chaîne

Exemples :
    python make_video.py episodes/demo
    python make_video.py episodes/ep01 --config channel.yaml
    python make_video.py episodes/ep01 --formats long,short
    python make_video.py episodes/ep01 --tts dummy        # test sans réseau
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permet d'exécuter le script directement (python make_video.py ...).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vpipeline import assemble, config, script_parser  # noqa: E402
from vpipeline.util import die, log, require_tool  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Voix + images -> vidéo (pipeline réutilisable par épisode).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("episode", help="Dossier de l'épisode (contient script.md + images/).")
    ap.add_argument("--script", help="Nom du script (défaut: script.md).")
    ap.add_argument("--images", help="Nom du sous-dossier images (défaut: images).")
    ap.add_argument("--config", help="Fichier de config (.yaml ou .json).")
    ap.add_argument("--out", help="Dossier de sortie (défaut: <épisode>/output).")
    ap.add_argument("--formats", help="Formats séparés par des virgules (long,short,square,1280x720).")
    ap.add_argument("--tts", help="Voix : windows (voix du PC) | fichier (ton mp3/wav) | dummy (silence).")
    ap.add_argument("--voice-file", dest="voice_file",
                    help="Fichier audio (ta voix) à utiliser comme bande-son ; "
                         "force la voix 'fichier'.")
    ap.add_argument("--transition", choices=["crossfade", "fade"],
                    help="Transition entre images (défaut: crossfade).")
    ap.add_argument("--no-intro", action="store_true", help="Désactive l'intro.")
    ap.add_argument("--no-motion", action="store_true", help="Désactive le zoom sur les images.")
    ap.add_argument("--auto-images", action="store_true",
                    help="Cherche et télécharge les images manquantes.")
    ap.add_argument("--image-provider", choices=["pixabay", "openverse", "ia"],
                    help="Images : pixabay (clé) | openverse (sans clé) | ia (générées, sans clé).")
    ap.add_argument("--pixabay-key", help="Clé API Pixabay (sinon $PIXABAY_API_KEY).")
    ap.add_argument("--write-script", metavar="SUJET",
                    help="Fait écrire le script.md par une IA à partir d'un sujet.")
    ap.add_argument("--segments", type=int, default=5,
                    help="Nombre de segments pour --write-script (défaut: 5).")
    ap.add_argument("--ai-provider", choices=["groq", "claude"],
                    help="IA pour --write-script (groq = gratuit ; claude = payant).")
    ap.add_argument("--groq-key", help="Clé API Groq (sinon $GROQ_API_KEY).")
    ap.add_argument("--anthropic-key", help="Clé API Claude (sinon $ANTHROPIC_API_KEY).")
    ap.add_argument("--keep-temp", action="store_true", help="Garde les fichiers intermédiaires.")
    args = ap.parse_args(argv)

    require_tool("ffmpeg")
    require_tool("ffprobe")

    ep_dir = Path(args.episode)
    if not ep_dir.is_dir():
        die(f"Dossier d'épisode introuvable : {ep_dir}")

    script_path = ep_dir / (args.script or "script.md")
    if not script_path.exists():
        # tolérance : script.txt
        alt = ep_dir / "script.txt"
        script_path = alt if alt.exists() else script_path
    images_dir = ep_dir / (args.images or "images")

    # Config : explicite, sinon config.yaml/json du dossier épisode, sinon défauts.
    cfg_path = args.config
    if not cfg_path:
        for name in ("config.yaml", "config.yml", "config.json"):
            if (ep_dir / name).exists():
                cfg_path = str(ep_dir / name)
                break
    cfg = config.load_config(cfg_path)

    # Surcharges CLI.
    if args.formats:
        cfg["formats"] = [f.strip() for f in args.formats.split(",") if f.strip()]
    if args.tts:
        cfg["tts"]["backend"] = args.tts
    if args.voice_file:
        cfg["tts"]["voice_file"] = args.voice_file
        cfg["tts"]["backend"] = "fichier"
    if args.transition:
        cfg["transition"] = args.transition
    if args.no_intro:
        cfg["intro"]["enabled"] = False
    if args.no_motion:
        cfg["motion"] = False
    if args.auto_images:
        cfg["images"]["auto"] = True
    if args.image_provider:
        cfg["images"]["provider"] = args.image_provider
    if args.pixabay_key:
        cfg["images"]["key"] = args.pixabay_key
    if args.ai_provider:
        cfg["ai"]["provider"] = args.ai_provider
    if args.groq_key:
        cfg["ai"]["key"] = args.groq_key
    if args.anthropic_key:
        cfg["ai"]["key"] = args.anthropic_key

    # Écriture du script par une IA (optionnel).
    if args.write_script:
        from vpipeline import ai_script
        log(f"L'IA rédige le script sur : « {args.write_script} »…")
        try:
            text = ai_script.generate_script(args.write_script, args.segments, cfg,
                                             cfg["ai"].get("key"))
        except RuntimeError as exc:
            die(str(exc))
        script_path = ep_dir / (args.script or "script.md")
        script_path.write_text(text, encoding="utf-8")
        log(f"Script écrit : {script_path}")

    if not cfg.get("font"):
        log("Aucune police .ttf trouvée : les textes à l'écran seront désactivés "
            "par ffmpeg. Renseigne 'font' dans la config.")

    auto_images = bool(cfg["images"]["auto"])
    episode = script_parser.parse_script(script_path, images_dir,
                                         allow_missing=auto_images)

    # Recherche automatique des images manquantes (Pixabay).
    if auto_images:
        from vpipeline import images as imagesmod
        imagesmod.auto_fetch(episode, cfg, images_dir)
        still = [i + 1 for i, s in enumerate(episode.segments) if s.image is None]
        if still:
            die(f"Images introuvables pour le(s) segment(s) {still}. "
                f"Ajoute-les manuellement ou modifie le texte/[text:].")

    log(f"Épisode : « {episode.title} » — {len(episode.segments)} segment(s).")

    out_dir = Path(args.out) if args.out else ep_dir / "output"
    work = out_dir / ".work"
    cache = ep_dir / ".cache"

    # 1) Voix (une seule fois, partagée entre tous les formats).
    seg_audios = assemble.synth_all(episode, cfg, cache)

    # 2) Vidéo par format.
    formats = config.resolve_formats(cfg)
    produced: list[Path] = []
    slug = _slug(episode.title) or ep_dir.name
    for fmt_name, w, h in formats:
        out_video = out_dir / f"{slug}__{fmt_name}.mp4"
        assemble.build(episode, seg_audios, cfg, w, h, fmt_name, work, out_video)
        produced.append(out_video)

    # 3) Nettoyage.
    if not args.keep_temp:
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    log("Terminé. Fichiers générés :")
    for p in produced:
        print(f"   - {p}")
        srt = p.with_suffix(".srt")
        if srt.exists():
            print(f"   - {srt}")
    return 0


def _slug(text: str) -> str:
    import re
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_-]+", "-", s)[:60]


if __name__ == "__main__":
    raise SystemExit(main())
