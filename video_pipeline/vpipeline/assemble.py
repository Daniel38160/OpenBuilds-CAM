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
    """Audio synthétisé d'un segment (indépendant du format vidéo)."""
    wav: Path
    speech: float   # durée de parole réelle (pour les sous-titres)


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
    backend = cfg["tts"]["backend"]
    voice = cfg["tts"].get("voice", "")
    rate = cfg["tts"].get("rate", "")
    out: list[SegAudio] = []
    for i, seg in enumerate(episode.segments):
        key = f"{backend}|{voice}|{rate}|{seg.narration}"
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        wav = cache_dir / f"seg_{h}.wav"
        if wav.exists():
            from .util import probe_duration
            dur = probe_duration(wav)
            log(f"segment {i + 1}/{len(episode.segments)} : audio en cache")
        else:
            log(f"segment {i + 1}/{len(episode.segments)} : synthèse voix…")
            dur = tts.synthesize(seg.narration, wav, cfg)
        out.append(SegAudio(wav=wav, speech=dur))
    return out


# --------------------------------------------------------------------------- #
# Filtres overlay (texte / bandeau / logo)
# --------------------------------------------------------------------------- #
def _drawtext(textfile: Path, font: str, fontsize: int, color: str,
              box_opacity: float, y_expr: str) -> str:
    parts = [
        f"fontfile='{_esc_path(font)}'" if font else "",
        f"textfile='{_esc_path(textfile)}'",
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
                intro_subtitle: str | None = None) -> None:
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

    # Fades (entrée/sortie) communs.
    if fade > 0 and duration > 2 * fade:
        vchain.append(f"fade=t=in:st=0:d={fade}")
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

    clips: list[Path] = []
    audios: list[Path] = []
    srt_entries: list[tuple[float, float, str]] = []
    timeline = 0.0

    # Intro optionnelle.
    if cfg["intro"]["enabled"]:
        idur_frames = _frames(float(cfg["intro"]["seconds"]), fps)
        idur = idur_frames / fps
        iclip = workdir / f"{fmt_name}_intro.mp4"
        iaud = workdir / f"{fmt_name}_intro.wav"
        bg = cfg["intro"]["background"]
        img = Path(bg) if (isinstance(bg, str) and Path(bg).exists()) else None
        _build_clip(
            image=img, duration=idur, W=W, H=H, cfg=cfg, workdir=workdir,
            out=iclip, caption=None, source=None,
            intro_title=cfg["intro"].get("title") or episode.title,
            intro_subtitle=cfg["intro"].get("subtitle"),
        )
        _silence(idur, iaud)
        clips.append(iclip)
        audios.append(iaud)
        timeline += idur

    # Segments.
    for i, (seg, sa) in enumerate(zip(episode.segments, seg_audios)):
        clip_dur_frames = _frames(sa.speech + gap, fps)
        clip_dur = clip_dur_frames / fps
        clip = workdir / f"{fmt_name}_seg{i:03d}.mp4"
        aud = workdir / f"{fmt_name}_seg{i:03d}.wav"
        _build_clip(
            image=seg.image, duration=clip_dur, W=W, H=H, cfg=cfg,
            workdir=workdir, out=clip, caption=seg.caption, source=seg.source,
        )
        _pad_audio(sa.wav, clip_dur, aud)
        clips.append(clip)
        audios.append(aud)
        if seg.narration:
            srt_entries.append((timeline, timeline + sa.speech, seg.narration))
        timeline += clip_dur

    # Concat vidéo (clips identiques -> copie sans ré-encodage).
    video_only = workdir / f"{fmt_name}_video.mp4"
    _concat_copy(clips, video_only, workdir / f"{fmt_name}_vlist.txt")

    # Concat audio voix.
    voice = workdir / f"{fmt_name}_voice.wav"
    _concat_audio(audios, voice, workdir / f"{fmt_name}_alist.txt")

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
