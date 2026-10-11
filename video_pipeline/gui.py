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
# Helpers métier (testables sans interface)
# --------------------------------------------------------------------------- #
STARTER_SCRIPT = """# Titre de l'épisode

[text: Mon premier point]
[source: ma-source.com]
Écris ici le texte que la voix va lire à voix haute.
Un paragraphe (séparé par une ligne vide) = un segment = une image.

[text: Deuxième point]
Ajoute autant de segments que tu veux. Mets tes images dans le
sous-dossier images/ en les nommant 01_..., 02_... pour l'ordre.

// Gag de fin optionnel : une image tenue, avec un bruitage et sans narration
// [img: oups.png]
// [audio: assets/pouet.wav]
"""


def create_episode(parent_dir: str | Path, name: str) -> Path:
    """Crée un dossier d'épisode prêt à l'emploi (script + images/ + assets/)."""
    safe = "".join(c for c in name.strip() if c.isalnum() or c in " -_").strip()
    safe = safe.replace(" ", "-").lower() or "nouvel-episode"
    ep = Path(parent_dir) / safe
    if ep.exists():
        raise FileExistsError(f"Le dossier existe déjà : {ep}")
    (ep / "images").mkdir(parents=True)
    (ep / "assets").mkdir(parents=True)
    (ep / "script.md").write_text(STARTER_SCRIPT, encoding="utf-8")
    return ep


def analyze_episode(ep_dir: str | Path) -> tuple[bool, str]:
    """Renvoie (ok, message court) décrivant l'épisode, sans lever d'exception."""
    import make_video  # noqa: F401  (assure le sys.path)
    from vpipeline import script_parser

    ep = Path(ep_dir)
    script = ep / "script.md"
    if not script.exists():
        script = ep / "script.txt"
    images_dir = ep / "images"
    if not script.exists():
        return False, "Pas de script.md dans ce dossier."

    n_imgs = len([p for p in images_dir.glob("*")
                  if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}]) \
        if images_dir.is_dir() else 0

    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    try:
        ep_obj = script_parser.parse_script(script, images_dir)
    except SystemExit:
        msg = err.getvalue().replace("[vpipeline] ERREUR:", "").strip()
        return False, msg.splitlines()[0] if msg else "Script invalide."
    except Exception as exc:
        return False, str(exc)
    finally:
        sys.stderr = old
    return True, f"« {ep_obj.title} » — {len(ep_obj.segments)} segment(s), {n_imgs} image(s)"


def icon_path() -> Path | None:
    for p in (HERE / "assets" / "app_icon.ico",):
        if p.exists():
            return p
    return None


# --------------------------------------------------------------------------- #
# Interface Tkinter
# --------------------------------------------------------------------------- #
def launch() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    st = load_settings()
    root = tk.Tk()
    root.title(APP_NAME)
    root.minsize(680, 600)

    # Icône de la fenêtre (meilleur effort selon la plateforme).
    ico = icon_path()
    if ico:
        try:
            root.iconbitmap(str(ico))           # Windows
        except Exception:
            try:
                png = HERE / "assets" / "app_icon_256.png"
                if png.exists():
                    root.iconphoto(True, tk.PhotoImage(file=str(png)))
            except Exception:
                pass

    pad = {"padx": 10, "pady": 6}
    header = ttk.Frame(root)
    header.pack(fill="x")
    ttk.Label(header, text="🎬  OpenBuilds Video",
              font=("", 15, "bold")).pack(side="left", padx=12, pady=(12, 2))
    ttk.Label(header, text="script + images → vidéo",
              foreground="#888").pack(side="left", pady=(12, 2))

    frm = ttk.Frame(root)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    row = 0
    ttk.Label(frm, text="Dossier de l'épisode", font=("", 10, "bold")).grid(
        row=row, column=0, sticky="w", **pad)
    episode_var = tk.StringVar(value=st.get("episode", ""))
    ttk.Entry(frm, textvariable=episode_var).grid(row=row, column=1, sticky="ew", **pad)

    btns = ttk.Frame(frm)
    btns.grid(row=row, column=2, **pad)

    def browse() -> None:
        d = filedialog.askdirectory(title="Choisis le dossier de l'épisode")
        if d:
            episode_var.set(d)

    def new_episode() -> None:
        parent = filedialog.askdirectory(title="Où créer le nouvel épisode ?")
        if not parent:
            return
        name = simpledialog.askstring(APP_NAME, "Nom du nouvel épisode :",
                                      parent=root)
        if not name:
            return
        try:
            ep = create_episode(parent, name)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        episode_var.set(str(ep))
        messagebox.showinfo(
            APP_NAME,
            f"Épisode créé :\n{ep}\n\n1) Mets tes images dans images/\n"
            f"2) Écris ta narration dans script.md\n3) Clique Générer.")

    ttk.Button(btns, text="Parcourir…", command=browse).pack(side="left")
    ttk.Button(btns, text="Nouvel épisode…", command=new_episode).pack(side="left", padx=(6, 0))

    row += 1
    info_var = tk.StringVar(value="")
    info_lbl = ttk.Label(frm, textvariable=info_var, foreground="#2a9d8f")
    info_lbl.grid(row=row, column=1, columnspan=2, sticky="w", padx=10)

    def refresh_info(*_a) -> None:
        ep = episode_var.get().strip()
        if ep and Path(ep).is_dir():
            ok, msg = analyze_episode(ep)
            info_var.set(("✓ " if ok else "⚠ ") + msg)
            info_lbl.config(foreground="#2a9d8f" if ok else "#e76f51")
        else:
            info_var.set("")
    episode_var.trace_add("write", refresh_info)

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
    ttk.Label(frm, text="Voix ElevenLabs").grid(row=row, column=0, sticky="w", **pad)
    el_voice_var = tk.StringVar(value=st.get("elevenlabs_voice", "Rachel"))
    el_voice_cb = ttk.Combobox(frm, textvariable=el_voice_var, values=["Rachel"])
    el_voice_cb.grid(row=row, column=1, sticky="ew", **pad)
    el_voice_map: dict[str, str] = {}   # nom affiché -> voice_id

    def load_voices() -> None:
        api = key_var.get().strip()
        if not api:
            messagebox.showinfo(APP_NAME, "Colle d'abord ta clé ElevenLabs.")
            return
        load_btn.config(state="disabled", text="…")

        def worker() -> None:
            try:
                from vpipeline import tts
                voices = tts.list_elevenlabs_voices(api)
            except Exception as exc:
                root.after(0, lambda: (load_btn.config(state="normal", text="Charger mes voix"),
                                       messagebox.showerror(APP_NAME, f"Impossible de charger les voix :\n{exc}")))
                return

            def apply() -> None:
                el_voice_map.clear()
                names = []
                for v in voices:
                    label = v["name"] + (f"  ({v['labels']})" if v["labels"] else "")
                    names.append(label)
                    el_voice_map[label] = v["voice_id"]
                    el_voice_map[v["name"]] = v["voice_id"]
                el_voice_cb.config(values=names or ["Rachel"])
                load_btn.config(state="normal", text="Charger mes voix")
                messagebox.showinfo(APP_NAME, f"{len(voices)} voix chargées. Choisis-en une dans la liste.")
            root.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    load_btn = ttk.Button(frm, text="Charger mes voix", command=load_voices)
    load_btn.grid(row=row, column=2, **pad)

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
    status_var = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status_var, foreground="#888").grid(
        row=row, column=2, sticky="e", **pad)

    row += 1
    frm.rowconfigure(row, weight=1)
    log = tk.Text(frm, height=14, wrap="word", state="disabled",
                  bg="#101418", fg="#e6e6e6", insertbackground="#e6e6e6")
    log.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)

    state = {"out_dir": None, "running": False, "t0": 0.0}

    import time

    def tick() -> None:
        if state["running"]:
            status_var.set(f"⏱ {int(time.time() - state['t0'])} s")
            root.after(500, tick)

    def append(txt: str) -> None:
        log.config(state="normal")
        log.insert("end", txt)
        log.see("end")
        log.config(state="disabled")

    def persist() -> None:
        save_settings({
            "episode": episode_var.get(), "tts": tts_var.get(),
            "elevenlabs_key": key_var.get(), "elevenlabs_voice": el_voice_var.get(),
            "edge_voice": edge_voice_var.get(),
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
        elapsed = int(time.time() - state["t0"]) if state["t0"] else 0
        gen_btn.config(state="normal", text="🎬  Générer la vidéo")
        if rc == 0:
            status_var.set(f"✓ fait en {elapsed} s")
            append(f"\n✅ Terminé en {elapsed} s.\n")
            if state["out_dir"]:
                open_btn.config(state="normal")
                open_output()   # ouvre directement le dossier de sortie
        else:
            status_var.set("échec")
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
        el_voice = el_voice_map.get(el_voice_var.get(), el_voice_var.get()).strip()
        argv = [ep, "--tts", tts_var.get(), "--formats", fmt_var.get(),
                "--transition", trans_var.get(), "--voice", edge_voice_var.get()]
        if el_voice:
            argv += ["--elevenlabs-voice", el_voice]
        if not intro_var.get():
            argv.append("--no-intro")
        if not motion_var.get():
            argv.append("--no-motion")

        log.config(state="normal"); log.delete("1.0", "end"); log.config(state="disabled")
        append(f"Génération de « {Path(ep).name} »…\n\n")
        open_btn.config(state="disabled")
        gen_btn.config(state="disabled", text="⏳  Génération en cours…")
        state["running"] = True
        import time
        state["t0"] = time.time()
        tick()
        threading.Thread(target=run_pipeline, args=(argv, log_q), daemon=True).start()
        root.after(120, poll)

    gen_btn.config(command=generate)
    root.mainloop()


if __name__ == "__main__":
    launch()
