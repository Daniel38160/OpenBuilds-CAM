"""Assemblage de la vidéo via ffmpeg.

Principe anti-dérive : chaque segment produit un clip vidéo d'un nombre ENTIER
de frames, et son audio est calé exactement sur la même durée (frames/fps).
La concaténation de clips identiques (même codec/résolution/fps) reste alors
parfaitement synchrone, segment après segment.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import tts
from .script_parser import Episode, Segment
from .util import log, require_tool, run, srt_timestamp, wrap_text


@dataclass
class SegAudio:
    """Audio d'un segment (indépendant du format vidéo)."""
    wav: Path
    speech: float        # durée de la piste (pour caler la vidéo)
    is_speech: bool = True   # True = narration (affichée en sous-titre)
    gap_after: bool = True   # petit silence après ce segment (coupé en mode 'fichier')


# --------------------------------------------------------------------------- #
# Échappement filtres ffmpeg
# --------------------------------------------------------------------------- #
def _esc_path(path: str | Path) -> str:
    """Échappe un chemin pour fontfile=/textfile= dans un filtre ffmpeg."""
    s = str(path).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def _frames(duration: float, fps: int) -> int:
    return max(1, int(round(duration * fps)))


# --------------------------------------------------------------------------- #
# TTS (fait une seule fois, indépendant du format ; mis en cache)
# --------------------------------------------------------------------------- #
def synth_all(episode: Episode, cfg: dict[str, Any], cache_dir: Path) -> list[SegAudio]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    tts.preflight(cfg)
    backend = cfg["tts"]["backend"].lower()
    voice = cfg["tts"].get("voice", "")
    rate = cfg["tts"].get("rate", "")
    from .util import probe_duration

    # Mode « fichier audio » : l'utilisateur fournit sa propre voix (un mp3/wav).
    # On répartit ce son sur les images/segments (voir _voicefile_audios).
    if backend == "fichier":
        return _voicefile_audios(episode, cfg, cache_dir)

    out: list[SegAudio] = []
    n = len(episode.segments)
    for i, seg in enumerate(episode.segments):
        # 1) Son fourni ([audio:]) -> on l'utilise tel quel (bruitage, sting…).
        if seg.audio is not None:
            h = hashlib.sha1(f"file|{seg.audio.resolve()}".encode()).hexdigest()[:16]
            wav = cache_dir / f"snd_{h}.wav"
            if not wav.exists():
                log(f"segment {i + 1}/{n} : son « {seg.audio.name} »")
                tts._to_wav(seg.audio, wav)
            dur = probe_duration(wav)
            out.append(SegAudio(wav=wav, speech=dur, is_speech=False))
            continue

        # 2) Pas de narration -> image fixe silencieuse (gag de fin, carton…).
        if not seg.narration.strip():
            hold = float(seg.hold if seg.hold is not None else cfg["still_seconds"])
            h = hashlib.sha1(f"hold|{hold:.3f}".encode()).hexdigest()[:16]
            wav = cache_dir / f"hold_{h}.wav"
            if not wav.exists():
                log(f"segment {i + 1}/{n} : image fixe ({hold:.1f}s)")
                _silence(hold, wav)
            out.append(SegAudio(wav=wav, speech=hold, is_speech=False))
            continue

        # 3) Narration -> synthèse vocale (mise en cache par texte).
        key = f"{backend}|{voice}|{rate}|{seg.narration}"
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        wav = cache_dir / f"seg_{h}.wav"
        if wav.exists():
            dur = probe_duration(wav)
            log(f"segment {i + 1}/{n} : audio en cache")
        else:
            log(f"segment {i + 1}/{n} : synthèse voix…")
            dur = tts.synthesize(seg.narration, wav, cfg)
        out.append(SegAudio(wav=wav, speech=dur, is_speech=True))
    return out


def _voicefile_audios(episode: Episode, cfg: dict[str, Any],
                      cache_dir: Path) -> list[SegAudio]:
    """Mode « fichier audio » : on utilise LE son fourni par l'utilisateur
    (sa propre voix) comme bande-son, réparti sur les segments/images.

    - Les segments avec un [audio:] explicite (bruitage de fin, sting) gardent
      leur son propre.
    - Les segments « muets » avec un [hold: N] gardent leur durée fixe.
    - Tous les autres segments se partagent la durée du fichier audio, au
      prorata de la longueur de leur narration (texte plus long = reste plus
      longtemps à l'écran). S'il n'y a aucune narration, part égale.
    """
    from .util import probe_duration

    vf = Path(cfg["tts"]["voice_file"])
    if not vf.exists():
        die(f"Fichier audio introuvable : {vf}")

    # 1) Normalise le fichier fourni (une seule fois, mis en cache).
    h = hashlib.sha1(f"voicefile|{vf.resolve()}|{vf.stat().st_mtime_ns}"
                     .encode()).hexdigest()[:16]
    master = cache_dir / f"voice_{h}.wav"
    if not master.exists():
        log(f"Préparation de ton fichier audio « {vf.name} »…")
        tts._to_wav(vf, master)
    total = probe_duration(master)
    fps = int(cfg["fps"])
    total_frames = max(1, int(round(total * fps)))

    n = len(episode.segments)

    def is_fixed(seg: Segment) -> bool:
        if seg.audio is not None:
            return True
        if not seg.narration.strip() and seg.hold is not None:
            return True
        return False

    voice_idx = [i for i, s in enumerate(episode.segments) if not is_fixed(s)]
    any_narration = any(s.narration.strip() for s in episode.segments)

    # Poids de chaque segment « voix » (longueur de narration, min 1).
    if voice_idx:
        weights = [max(1, len(episode.segments[i].narration.strip()))
                   if any_narration else 1 for i in voice_idx]
        tw = sum(weights)
        # Répartition en nombre ENTIER de frames (le dernier prend le reste).
        alloc: dict[int, int] = {}
        acc = 0
        for k, i in enumerate(voice_idx):
            if k == len(voice_idx) - 1:
                alloc[i] = max(1, total_frames - acc)
            else:
                f = max(1, int(round(total_frames * weights[k] / tw)))
                alloc[i] = f
                acc += f
    else:
        alloc = {}

    out: list[SegAudio] = []
    cursor_frames = 0  # position de lecture dans le fichier audio (en frames)
    for i, seg in enumerate(episode.segments):
        # a) [audio:] explicite -> son fourni tel quel.
        if seg.audio is not None:
            hh = hashlib.sha1(f"file|{seg.audio.resolve()}".encode()).hexdigest()[:16]
            wav = cache_dir / f"snd_{hh}.wav"
            if not wav.exists():
                log(f"segment {i + 1}/{n} : son « {seg.audio.name} »")
                tts._to_wav(seg.audio, wav)
            out.append(SegAudio(wav=wav, speech=probe_duration(wav),
                                is_speech=False))
            continue

        # b) image muette tenue ([hold:]) -> silence de durée fixe.
        if not seg.narration.strip() and seg.hold is not None:
            hold = float(seg.hold)
            hh = hashlib.sha1(f"hold|{hold:.3f}".encode()).hexdigest()[:16]
            wav = cache_dir / f"hold_{hh}.wav"
            if not wav.exists():
                _silence(hold, wav)
            out.append(SegAudio(wav=wav, speech=hold, is_speech=False))
            continue

        # c) segment « voix » -> tranche contiguë du fichier audio.
        frames = alloc.get(i, 1)
        start = cursor_frames / fps
        dur = frames / fps
        cursor_frames += frames
        hh = hashlib.sha1(f"slice|{master.name}|{start:.3f}|{dur:.3f}"
                          .encode()).hexdigest()[:16]
        wav = cache_dir / f"vslice_{hh}.wav"
        if not wav.exists():
            log(f"segment {i + 1}/{n} : extrait audio ({dur:.1f}s)")
            _slice_audio(master, start, dur, wav)
        # is_speech=True -> sous-titre affiché ; gap_after=False -> voix continue.
        out.append(SegAudio(wav=wav, speech=dur, is_speech=True, gap_after=False))
    return out


def _slice_audio(src: Path, start: float, dur: float, out: Path) -> None:
    """Extrait [start, start+dur] du WAV normalisé `src`."""
    ffmpeg = require_tool("ffmpeg")
    run([ffmpeg, "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
         "-ar", str(tts.TARGET_RATE), "-ac", str(tts.TARGET_CH), str(out)])


# --------------------------------------------------------------------------- #
# Filtres overlay (texte / bandeau / logo)
# --------------------------------------------------------------------------- #
def _drawtext(textfile: Path, font: str, fontsize: int, color: str,
              box_opacity: float, y_expr: str) -> str:
    parts = [
        f"fontfile='{_esc_path(font)}'" if font else "",
        f"textfile='{_esc_path(textfile)}'",
        "expansion=none",   # texte littéral : autorise % (ex: « 10% ») et autres
        f"fontcolor={color}",
        f"fontsize={fontsize}",
        "box=1",
        f"boxcolor=black@{box_opacity}",
        "boxborderw=22",
        "line_spacing=8",
        "x=(w-text_w)/2",
        f"y={y_expr}",
    ]
    return "drawtext=" + ":".join(p for p in parts if p)


def _caption_y(position: str) -> str:
    return {
        "top": "80",
        "center": "(h-text_h)/2",
        "bottom": "h-text_h-90",
    }.get(position, "h-text_h-90")


def _logo_xy(position: str, margin: int) -> str:
    return {
        "top-right": f"W-w-{margin}:{margin}",
        "top-left": f"{margin}:{margin}",
        "bottom-right": f"W-w-{margin}:H-h-{margin}",
        "bottom-left": f"{margin}:H-h-{margin}",
    }.get(position, f"W-w-{margin}:{margin}")


# --------------------------------------------------------------------------- #
# Clips
# --------------------------------------------------------------------------- #
def _build_clip(*, image: Path | None, duration: float, W: int, H: int,
                cfg: dict[str, Any], workdir: Path, out: Path,
                caption: str | None, source: str | None,
                intro_title: str | None = None,
                intro_subtitle: str | None = None,
                fade_in: bool = True, fade_out: bool = True) -> None:
    """Construit un clip vidéo (sans audio) d'une durée exacte `duration`."""
    ffmpeg = require_tool("ffmpeg")
    fps = int(cfg["fps"])
    frames = _frames(duration, fps)
    fade = float(cfg["fade_seconds"])
    font = cfg["font"] or ""
    bg = cfg["background_color"]
    motion = bool(cfg["motion"]) and image is not None and intro_title is None

    inputs: list[str] = []
    vchain: list[str] = []

    if intro_title is not None:
        # Intro : fond uni (ou image) + titre + sous-titre.
        if image is not None:
            inputs += ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(image)]
            vchain.append(
                f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1,fps={fps}"
            )
        else:
            inputs += ["-f", "lavfi", "-t", f"{duration:.3f}",
                       "-i", f"color=c={bg}:s={W}x{H}:r={fps}"]
            vchain.append("setsar=1")
    elif motion:
        # Image unique -> zoompan génère exactement `frames` frames (zoom doux).
        inputs += ["-i", str(image)]
        z = "min(zoom+0.0006,1.12)"
        vchain.append(
            f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
            f"crop={W * 2}:{H * 2},"
            f"zoompan=z='{z}':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={W}x{H}:fps={fps},setsar=1"
        )
    else:
        inputs += ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(image)]
        vchain.append(
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={fps}"
        )

    # Fades d'entrée / sortie (en crossfade, seuls le 1er et le dernier clip
    # en ont ; les transitions entre clips sont gérées par xfade).
    if fade > 0 and duration > 2 * fade:
        if fade_in:
            vchain.append(f"fade=t=in:st=0:d={fade}")
        if fade_out:
            vchain.append(f"fade=t=out:st={duration - fade:.3f}:d={fade}")

    # Titre / sous-titre d'intro.
    if intro_title is not None:
        tf = workdir / f"{out.stem}_title.txt"
        tf.write_text(wrap_text(intro_title, 26), encoding="utf-8")
        vchain.append(_drawtext(tf, font, int(cfg["intro"]["fontsize"]),
                                "white", 0.0, "(h-text_h)/2-40"))
        if intro_subtitle:
            sf = workdir / f"{out.stem}_sub.txt"
            sf.write_text(wrap_text(intro_subtitle, 40), encoding="utf-8")
            vchain.append(_drawtext(sf, font, int(cfg["intro"]["fontsize"] * 0.5),
                                    "0xCCCCCC", 0.0, "(h-text_h)/2+70"))

    # Texte à l'écran du segment.
    if caption and cfg["captions"]["enabled"]:
        cf = workdir / f"{out.stem}_cap.txt"
        cf.write_text(wrap_text(caption, int(cfg["captions"]["max_chars_per_line"])),
                      encoding="utf-8")
        vchain.append(_drawtext(cf, font, int(cfg["captions"]["fontsize"]),
                                cfg["captions"]["color"],
                                float(cfg["captions"]["box_opacity"]),
                                _caption_y(cfg["captions"]["position"])))

    # Bandeau sources (bas de l'écran, discret).
    if source and cfg["source_banner"]["enabled"]:
        bf = workdir / f"{out.stem}_src.txt"
        bf.write_text(f"Sources : {source}", encoding="utf-8")
        vchain.append(_drawtext(bf, font, int(cfg["source_banner"]["fontsize"]),
                                cfg["source_banner"]["color"],
                                float(cfg["source_banner"]["box_opacity"]),
                                "h-text_h-26"))

    # Logo overlay (entrée image supplémentaire).
    logo = cfg["logo"]["path"]
    use_logo = bool(logo) and Path(logo).exists()
    enc = _encode_opts(cfg)

    if use_logo:
        inputs += ["-i", str(logo)]
        base = ",".join(vchain)
        lh = int(cfg["logo"]["height"])
        xy = _logo_xy(cfg["logo"]["position"], int(cfg["logo"]["margin"]))
        fc = (f"[0:v]{base}[base];[1:v]scale=-1:{lh}[lg];"
              f"[base][lg]overlay={xy}:format=auto[out]")
        cmd = [ffmpeg, "-y", *inputs, "-filter_complex", fc, "-map", "[out]"]
    else:
        cmd = [ffmpeg, "-y", *inputs, "-vf", ",".join(vchain)]

    cmd += ["-frames:v", str(frames), *enc, "-an", str(out)]
    run(cmd)


def _encode_opts(cfg: dict[str, Any]) -> list[str]:
    fps = int(cfg["fps"])
    out = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
           "-preset", str(cfg["output"]["preset"])]
    if cfg["output"].get("video_bitrate"):
        out += ["-b:v", str(cfg["output"]["video_bitrate"])]
    else:
        out += ["-crf", str(cfg["output"]["crf"])]
    return out


def _pad_audio(src: Path, duration: float, out: Path) -> None:
    """Cale un WAV sur une durée exacte (silence ajouté au besoin)."""
    ffmpeg = require_tool("ffmpeg")
    run([ffmpeg, "-y", "-i", str(src), "-af", "apad", "-t", f"{duration:.3f}",
         "-ar", str(tts.TARGET_RATE), "-ac", str(tts.TARGET_CH), str(out)])


def _silence(duration: float, out: Path) -> None:
    ffmpeg = require_tool("ffmpeg")
    run([ffmpeg, "-y", "-f", "lavfi",
         "-i", f"anullsrc=r={tts.TARGET_RATE}:cl=mono",
         "-t", f"{duration:.3f}", str(out)])


# --------------------------------------------------------------------------- #
# Orchestration d'un format
# --------------------------------------------------------------------------- #
def build(episode: Episode, seg_audios: list[SegAudio], cfg: dict[str, Any],
          W: int, H: int, fmt_name: str, workdir: Path, out_video: Path) -> Path:
    fps = int(cfg["fps"])
    gap = float(cfg["audio"]["gap_seconds"])
    workdir.mkdir(parents=True, exist_ok=True)

    crossfade = str(cfg.get("transition", "crossfade")).lower() == "crossfade"
    fade = float(cfg["fade_seconds"])
    # Recouvrement du crossfade, calé sur une frame entière.
    xf = (_frames(fade, fps) / fps) if (crossfade and fade > 0) else 0.0

    # 1) On prépare la liste des "parties" (intro + segments) : pour chacune,
    #    sa durée audio (naturelle) et sa durée vidéo (allongée de xf pour le
    #    recouvrement, sauf la première partie).
    @dataclass
    class _Part:
        clip: Path
        audio: Path
        render_dur: float   # durée du clip vidéo
        audio_dur: float    # durée de la piste audio (= position sur la timeline)
        speech: float       # durée de parole réelle (sous-titres)
        narration: str

    specs: list[tuple] = []  # (image, audio_dur, caption, source, speech, narration, is_intro, intro_sub)

    if cfg["intro"]["enabled"]:
        idur = _frames(float(cfg["intro"]["seconds"]), fps) / fps
        bg = cfg["intro"]["background"]
        img = Path(bg) if (isinstance(bg, str) and Path(bg).exists()) else None
        specs.append((img, idur, None, None, 0.0, "",
                      cfg["intro"].get("title") or episode.title,
                      cfg["intro"].get("subtitle")))

    for seg, sa in zip(episode.segments, seg_audios):
        extra = gap if (sa.is_speech and sa.gap_after) else 0.0   # petit silence après la voix
        audio_dur = _frames(sa.speech + extra, fps) / fps
        specs.append((seg.image, audio_dur, seg.caption, seg.source,
                      sa.speech if sa.is_speech else 0.0,
                      seg.narration if sa.is_speech else "", None, None))

    # On récupère le wav de chaque partie (intro = silence, sinon audio déjà prêt).
    part_wavs: list[Path] = []
    if cfg["intro"]["enabled"]:
        iaud = workdir / f"{fmt_name}_intro.wav"
        _silence(specs[0][1], iaud)
        part_wavs.append(iaud)
    part_wavs += [sa.wav for sa in seg_audios]

    # 2) On fabrique clips + pistes audio calées, et la timeline des sous-titres.
    n = len(specs)
    parts: list[_Part] = []
    srt_entries: list[tuple[float, float, str]] = []
    timeline = 0.0
    for i, (image, audio_dur, caption, source, speech, narration,
            intro_title, intro_sub) in enumerate(specs):
        render_dur = audio_dur + (xf if i > 0 else 0.0)
        clip = workdir / f"{fmt_name}_clip{i:03d}.mp4"
        aud = workdir / f"{fmt_name}_clip{i:03d}.wav"
        _build_clip(
            image=image, duration=render_dur, W=W, H=H, cfg=cfg,
            workdir=workdir, out=clip, caption=caption, source=source,
            intro_title=intro_title, intro_subtitle=intro_sub,
            fade_in=(i == 0) or not crossfade,
            fade_out=(i == n - 1) or not crossfade,
        )
        _pad_audio(part_wavs[i], audio_dur, aud)
        if narration:
            srt_entries.append((timeline, timeline + speech, narration))
        timeline += audio_dur
        parts.append(_Part(clip, aud, render_dur, audio_dur, speech, narration))

    # 3) Montage vidéo.
    video_only = workdir / f"{fmt_name}_video.mp4"
    clips = [p.clip for p in parts]
    if crossfade and n > 1 and xf > 0:
        _concat_xfade(clips, [p.render_dur for p in parts], xf, cfg, video_only)
    else:
        _concat_copy(clips, video_only, workdir / f"{fmt_name}_vlist.txt")

    # Concat audio.
    voice = workdir / f"{fmt_name}_voice.wav"
    _concat_audio([p.audio for p in parts], voice, workdir / f"{fmt_name}_alist.txt")

    # Mix musique de fond éventuelle.
    final_audio = voice
    music = cfg["music"]["path"]
    if music and Path(music).exists():
        final_audio = workdir / f"{fmt_name}_mix.wav"
        _mix_music(voice, Path(music), timeline, cfg, final_audio)

    # Muxage final.
    out_video.parent.mkdir(parents=True, exist_ok=True)
    _mux(video_only, final_audio, cfg, out_video)

    # Sous-titres.
    _write_srt(srt_entries, out_video.with_suffix(".srt"))
    log(f"[{fmt_name}] vidéo : {out_video}  ({timeline:.1f}s)")
    return out_video


def _concat_copy(clips: list[Path], out: Path, listfile: Path) -> None:
    ffmpeg = require_tool("ffmpeg")
    listfile.write_text(
        "".join(f"file '{c.resolve().as_posix()}'\n" for c in clips),
        encoding="utf-8",
    )
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(out)])


def _concat_xfade(clips: list[Path], render_durs: list[float], xf: float,
                  cfg: dict[str, Any], out: Path) -> None:
    """Enchaîne les clips en fondu enchaîné (xfade). Chaque clip i>0 a été
    rendu `xf` secondes plus long pour alimenter le recouvrement ; la durée
    finale vaut donc exactement la somme des durées audio."""
    ffmpeg = require_tool("ffmpeg")
    kind = str(cfg.get("crossfade_type", "fade"))  # fade, dissolve, wipeleft, …
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]

    # Chaînage : offset = longueur cumulée courante - xf.
    filters: list[str] = []
    prev = "[0:v]"
    running = render_durs[0]
    for i in range(1, len(clips)):
        offset = running - xf
        label = f"[x{i}]" if i < len(clips) - 1 else "[vout]"
        filters.append(
            f"{prev}[{i}:v]xfade=transition={kind}:duration={xf:.3f}:"
            f"offset={offset:.3f}{label}"
        )
        prev = label
        running = running + render_durs[i] - xf

    fc = ";".join(filters)
    run([ffmpeg, "-y", *inputs, "-filter_complex", fc, "-map", "[vout]",
         *_encode_opts(cfg), "-an", str(out)])


def _concat_audio(auds: list[Path], out: Path, listfile: Path) -> None:
    ffmpeg = require_tool("ffmpeg")
    listfile.write_text(
        "".join(f"file '{a.resolve().as_posix()}'\n" for a in auds),
        encoding="utf-8",
    )
    # WAV identiques -> concat demuxer, puis ré-encodage WAV propre.
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-ar", str(tts.TARGET_RATE), "-ac", str(tts.TARGET_CH), str(out)])


def _mix_music(voice: Path, music: Path, total: float, cfg: dict[str, Any],
               out: Path) -> None:
    ffmpeg = require_tool("ffmpeg")
    vol = float(cfg["music"]["volume"])
    fade = float(cfg["music"]["fade_seconds"])
    st_out = max(0.0, total - fade)
    run([
        ffmpeg, "-y", "-i", str(voice), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex",
        (f"[1:a]volume={vol},afade=t=in:st=0:d={fade},"
         f"afade=t=out:st={st_out:.3f}:d={fade}[bg];"
         f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]"),
        "-map", "[a]", "-ar", str(tts.TARGET_RATE), "-ac", "2", str(out),
    ])


def _mux(video: Path, audio: Path, cfg: dict[str, Any], out: Path) -> None:
    ffmpeg = require_tool("ffmpeg")
    run([ffmpeg, "-y", "-i", str(video), "-i", str(audio),
         "-c:v", "copy", "-c:a", "aac", "-b:a", str(cfg["audio"]["bitrate"]),
         "-shortest", "-movflags", "+faststart", str(out)])


def _write_srt(entries: list[tuple[float, float, str]], out: Path) -> None:
    lines: list[str] = []
    for i, (start, end, text) in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
