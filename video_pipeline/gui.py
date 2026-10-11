#!/usr/bin/env python3
"""Interface graphique (Windows / macOS / Linux) pour le pipeline vidéo.

Une fenêtre simple : choisir le dossier d'épisode, la voix, le format,
coller sa clé ElevenLabs (mémorisée), cliquer « Générer ». La vidéo se
fabrique en tâche de fond et la progression s'affiche en direct.

- Aucune dépendance externe : Tkinter est fourni avec Python.
- Empaquetable en .exe autonome avec PyInstaller (voir build_windows.bat).
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import queue
from pathlib import Path

APP_NAME = "OpenBuilds Video"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# --------------------------------------------------------------------------- #
# Réglages persistés (clé API, derniers choix) — dans le dossier utilisateur.
# --------------------------------------------------------------------------- #
def _settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "OpenBuildsVideo"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        _settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# ffmpeg : on cherche un ffmpeg embarqué à côté de l'appli, sinon le PATH.
# --------------------------------------------------------------------------- #
def bootstrap_ffmpeg() -> bool:
    """Ajoute au PATH un ffmpeg embarqué (bin/ à côté de l'exe) s'il existe.
    Retourne True si ffmpeg est trouvable."""
    import shutil

    roots = [HERE]
    if getattr(sys, "frozen", False):           # exe PyInstaller
        roots.insert(0, Path(sys.executable).resolve().parent)
    for root in roots:
        for sub in (root, root / "bin", root / "ffmpeg", root / "ffmpeg" / "bin"):
            exe = sub / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if exe.exists():
                os.environ["PATH"] = str(sub) + os.pathsep + os.environ.get("PATH", "")
                return True
    return shutil.which("ffmpeg") is not None


# --------------------------------------------------------------------------- #
# Exécution du pipeline en tâche de fond, logs redirigés vers une file.
# --------------------------------------------------------------------------- #
class _QueueWriter(io.TextIOBase):
    def __init__(self, q: "queue.Queue[str]") -> None:
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(s)
        return len(s)

    def flush(self) -> None:  # noqa: D401
        pass


def run_pipeline(argv: list[str], log_q: "queue.Queue[str]") -> None:
    """Appelle make_video.main(argv) en capturant la sortie vers log_q.
    Poste ('__DONE__', rc) ou ('__ERROR__', message) à la fin."""
    import make_video

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _QueueWriter(log_q)  # type: ignore[assignment]
    try:
        rc = make_video.main(argv)
        log_q.put(f"__RESULT__{int(rc or 0)}")
    except SystemExit as exc:                       # util.die()
        log_q.put(f"__RESULT__{int(exc.code or 1)}")
    except Exception as exc:                          # garde-fou
        log_q.put(f"\n[erreur] {exc}\n__RESULT__1")
    finally:
        sys.stdout, sys.stderr = old_out, old_err


# --------------------------------------------------------------------------- #
# Interface Tkinter
# --------------------------------------------------------------------------- #
def launch() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    st = load_settings()
    root = tk.Tk()
    root.title(APP_NAME)
    root.minsize(640, 540)

    pad = {"padx": 10, "pady": 6}
    frm = ttk.Frame(root)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    row = 0
    ttk.Label(frm, text="Dossier de l'épisode", font=("", 10, "bold")).grid(
        row=row, column=0, sticky="w", **pad)
    episode_var = tk.StringVar(value=st.get("episode", ""))
    ttk.Entry(frm, textvariable=episode_var).grid(row=row, column=1, sticky="ew", **pad)

    def browse() -> None:
        d = filedialog.askdirectory(title="Choisis le dossier de l'épisode")
        if d:
            episode_var.set(d)
    ttk.Button(frm, text="Parcourir…", command=browse).grid(row=row, column=2, **pad)

    row += 1
    ttk.Label(frm, text="Voix").grid(row=row, column=0, sticky="w", **pad)
    tts_var = tk.StringVar(value=st.get("tts", "elevenlabs"))
    ttk.Combobox(frm, textvariable=tts_var, state="readonly",
                 values=["elevenlabs", "edge", "piper", "espeak", "dummy"]).grid(
        row=row, column=1, sticky="w", **pad)

    row += 1
    ttk.Label(frm, text="Clé ElevenLabs").grid(row=row, column=0, sticky="w", **pad)
    key_var = tk.StringVar(value=st.get("elevenlabs_key", ""))
    key_entry = ttk.Entry(frm, textvariable=key_var, show="•")
    key_entry.grid(row=row, column=1, sticky="ew", **pad)
    show_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="voir", variable=show_var,
                    command=lambda: key_entry.config(show="" if show_var.get() else "•")
                    ).grid(row=row, column=2, **pad)

    row += 1
    ttk.Label(frm, text="Voix edge (si backend edge)").grid(row=row, column=0, sticky="w", **pad)
    edge_voice_var = tk.StringVar(value=st.get("edge_voice", "fr-FR-DeniseNeural"))
    ttk.Entry(frm, textvariable=edge_voice_var).grid(row=row, column=1, sticky="w", **pad)

    row += 1
    ttk.Label(frm, text="Format").grid(row=row, column=0, sticky="w", **pad)
    fmt_var = tk.StringVar(value=st.get("formats", "long"))
    ttk.Combobox(frm, textvariable=fmt_var, state="readonly",
                 values=["long", "short", "square", "long,short"]).grid(
        row=row, column=1, sticky="w", **pad)

    row += 1
    ttk.Label(frm, text="Transition").grid(row=row, column=0, sticky="w", **pad)
    trans_var = tk.StringVar(value=st.get("transition", "crossfade"))
    ttk.Combobox(frm, textvariable=trans_var, state="readonly",
                 values=["crossfade", "fade"]).grid(row=row, column=1, sticky="w", **pad)

    row += 1
    opts = ttk.Frame(frm)
    opts.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
    intro_var = tk.BooleanVar(value=st.get("intro", True))
    motion_var = tk.BooleanVar(value=st.get("motion", True))
    ttk.Checkbutton(opts, text="Intro", variable=intro_var).pack(side="left", padx=6)
    ttk.Checkbutton(opts, text="Zoom (Ken Burns)", variable=motion_var).pack(side="left", padx=6)

    row += 1
    gen_btn = ttk.Button(frm, text="🎬  Générer la vidéo")
    gen_btn.grid(row=row, column=0, **pad)
    open_btn = ttk.Button(frm, text="Ouvrir le dossier de sortie", state="disabled")
    open_btn.grid(row=row, column=1, sticky="w", **pad)

    row += 1
    frm.rowconfigure(row, weight=1)
    log = tk.Text(frm, height=14, wrap="word", state="disabled",
                  bg="#101418", fg="#e6e6e6", insertbackground="#e6e6e6")
    log.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)

    state = {"out_dir": None, "running": False}

    def append(txt: str) -> None:
        log.config(state="normal")
        log.insert("end", txt)
        log.see("end")
        log.config(state="disabled")

    def persist() -> None:
        save_settings({
            "episode": episode_var.get(), "tts": tts_var.get(),
            "elevenlabs_key": key_var.get(), "edge_voice": edge_voice_var.get(),
            "formats": fmt_var.get(), "transition": trans_var.get(),
            "intro": intro_var.get(), "motion": motion_var.get(),
        })

    log_q: "queue.Queue[str]" = queue.Queue()

    def poll() -> None:
        try:
            while True:
                msg = log_q.get_nowait()
                if msg.startswith("__RESULT__"):
                    rc = int(msg.replace("__RESULT__", "") or "1")
                    finish(rc)
                else:
                    append(msg)
        except queue.Empty:
            pass
        if state["running"]:
            root.after(120, poll)

    def finish(rc: int) -> None:
        state["running"] = False
        gen_btn.config(state="normal", text="🎬  Générer la vidéo")
        if rc == 0:
            append("\n✅ Terminé.\n")
            if state["out_dir"]:
                open_btn.config(state="normal")
        else:
            append("\n❌ Échec (voir les messages ci-dessus).\n")

    def open_output() -> None:
        d = state["out_dir"]
        if not d:
            return
        if os.name == "nt":
            os.startfile(d)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{d}"')
        else:
            os.system(f'xdg-open "{d}"')
    open_btn.config(command=open_output)

    def generate() -> None:
        if state["running"]:
            return
        ep = episode_var.get().strip()
        if not ep or not Path(ep).is_dir():
            messagebox.showerror(APP_NAME, "Choisis un dossier d'épisode valide.")
            return
        if tts_var.get() == "elevenlabs" and not key_var.get().strip():
            messagebox.showerror(APP_NAME, "Colle ta clé ElevenLabs (ou choisis la voix « edge » / « dummy »).")
            return
        if not bootstrap_ffmpeg():
            messagebox.showerror(
                APP_NAME,
                "ffmpeg est introuvable.\n\nInstalle-le (winget install Gyan.FFmpeg) "
                "ou place ffmpeg.exe dans un sous-dossier « bin » à côté de l'appli.")
            return

        persist()
        if key_var.get().strip():
            os.environ["ELEVENLABS_API_KEY"] = key_var.get().strip()

        out_dir = Path(ep) / "output"
        state["out_dir"] = str(out_dir)
        argv = [ep, "--tts", tts_var.get(), "--formats", fmt_var.get(),
                "--transition", trans_var.get(), "--voice", edge_voice_var.get()]
        if not intro_var.get():
            argv.append("--no-intro")
        if not motion_var.get():
            argv.append("--no-motion")

        log.config(state="normal"); log.delete("1.0", "end"); log.config(state="disabled")
        append(f"Génération de « {Path(ep).name} »…\n\n")
        open_btn.config(state="disabled")
        gen_btn.config(state="disabled", text="⏳  Génération en cours…")
        state["running"] = True
        threading.Thread(target=run_pipeline, args=(argv, log_q), daemon=True).start()
        root.after(120, poll)

    gen_btn.config(command=generate)
    root.mainloop()


if __name__ == "__main__":
    launch()
