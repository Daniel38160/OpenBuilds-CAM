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

APP_NAME = "Générateur de vidéo"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# --------------------------------------------------------------------------- #
# Réglages persistés (clé API, derniers choix) — dans le dossier utilisateur.
# --------------------------------------------------------------------------- #
def _settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "GenerateurVideo"
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
    ttk.Label(header, text="🎬  Générateur de vidéo",
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
    claude_btn = ttk.Button(btns, text="✍️ Script avec l'IA")
    claude_btn.pack(side="left", padx=(6, 0))

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
    tts_var = tk.StringVar(value=st.get("tts", "streamelements"))
    ttk.Combobox(frm, textvariable=tts_var, state="readonly",
                 values=["streamelements", "elevenlabs", "edge", "piper", "espeak", "dummy"]).grid(
        row=row, column=1, sticky="w", **pad)
    ttk.Label(frm, text="streamelements = gratuit FR, sans clé", foreground="#888").grid(
        row=row, column=2, sticky="w", **pad)

    row += 1
    ttk.Label(frm, text="Voix gratuite (StreamElements)").grid(row=row, column=0, sticky="w", **pad)
    se_voice_var = tk.StringVar(value=st.get("se_voice", "Mathieu"))
    ttk.Combobox(frm, textvariable=se_voice_var, state="readonly",
                 values=["Mathieu", "Celine", "Lea", "Chantal"]).grid(
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
                msg = f"{type(exc).__name__}: {exc}"
                root.after(0, lambda m=msg: (load_btn.config(state="normal", text="Charger mes voix"),
                                             messagebox.showerror(
                                                 APP_NAME,
                                                 "Impossible de charger les voix :\n" + m +
                                                 "\n\nAstuce : colle directement l'ID de la voix "
                                                 "(depuis le site ElevenLabs) dans « Voix ElevenLabs ».")))
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
                persist()   # mémorise la clé dès qu'elle a servi
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
    ttk.Label(frm, text="Banque d'images").grid(row=row, column=0, sticky="w", **pad)
    imgprov_var = tk.StringVar(value=st.get("image_provider", "pixabay"))
    ttk.Combobox(frm, textvariable=imgprov_var, state="readonly",
                 values=["pixabay", "openverse", "ia"]).grid(row=row, column=1, sticky="w", **pad)
    ttk.Label(frm, text="openverse / ia = sans clé", foreground="#888").grid(
        row=row, column=2, sticky="w", **pad)

    row += 1
    ttk.Label(frm, text="Clé Pixabay (si Pixabay)").grid(row=row, column=0, sticky="w", **pad)
    pix_var = tk.StringVar(value=st.get("pixabay_key", ""))
    pix_entry = ttk.Entry(frm, textvariable=pix_var, show="•")
    pix_entry.grid(row=row, column=1, sticky="ew", **pad)
    pix_show = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="voir", variable=pix_show,
                    command=lambda: pix_entry.config(show="" if pix_show.get() else "•")
                    ).grid(row=row, column=2, **pad)

    row += 1
    ttk.Label(frm, text="IA (écrire le script)").grid(row=row, column=0, sticky="w", **pad)
    ai_prov_var = tk.StringVar(value=st.get("ai_provider", "groq"))
    ttk.Combobox(frm, textvariable=ai_prov_var, state="readonly",
                 values=["groq", "claude"]).grid(row=row, column=1, sticky="w", **pad)
    ttk.Label(frm, text="groq = gratuit", foreground="#888").grid(
        row=row, column=2, sticky="w", **pad)

    # Une clé par fournisseur, mémorisées séparément ; le champ bascule selon le choix.
    ia_keys = {"groq": st.get("groq_key", ""), "claude": st.get("anthropic_key", "")}
    _cur = [ai_prov_var.get()]

    row += 1
    ttk.Label(frm, text="Clé IA").grid(row=row, column=0, sticky="w", **pad)
    ai_key_var = tk.StringVar(value=ia_keys.get(_cur[0], ""))
    ai_entry = ttk.Entry(frm, textvariable=ai_key_var, show="•")
    ai_entry.grid(row=row, column=1, sticky="ew", **pad)
    ai_show = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="voir", variable=ai_show,
                    command=lambda: ai_entry.config(show="" if ai_show.get() else "•")
                    ).grid(row=row, column=2, **pad)

    def _on_ai_prov(*_a) -> None:
        ia_keys[_cur[0]] = ai_key_var.get()      # sauve la clé du fournisseur précédent
        _cur[0] = ai_prov_var.get()
        ai_key_var.set(ia_keys.get(_cur[0], ""))  # charge celle du nouveau
    ai_prov_var.trace_add("write", _on_ai_prov)

    row += 1
    opts = ttk.Frame(frm)
    opts.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
    intro_var = tk.BooleanVar(value=st.get("intro", True))
    motion_var = tk.BooleanVar(value=st.get("motion", True))
    autoimg_var = tk.BooleanVar(value=st.get("auto_images", False))
    ttk.Checkbutton(opts, text="Intro", variable=intro_var).pack(side="left", padx=6)
    ttk.Checkbutton(opts, text="Zoom (Ken Burns)", variable=motion_var).pack(side="left", padx=6)
    ttk.Checkbutton(opts, text="Chercher les images automatiquement",
                    variable=autoimg_var).pack(side="left", padx=6)

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
            "pixabay_key": pix_var.get(), "auto_images": autoimg_var.get(),
            "image_provider": imgprov_var.get(),
            "se_voice": se_voice_var.get(),
            "ai_provider": ai_prov_var.get(),
            "groq_key": (ai_key_var.get() if _cur[0] == "groq" else ia_keys.get("groq", "")),
            "anthropic_key": (ai_key_var.get() if _cur[0] == "claude" else ia_keys.get("claude", "")),
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
        if (autoimg_var.get() and imgprov_var.get() == "pixabay"
                and not pix_var.get().strip()):
            # Pas de clé Pixabay : on bascule sur Openverse (sans clé), on prévient juste.
            if not messagebox.askyesno(
                    APP_NAME,
                    "Pixabay est choisi mais aucune clé n'est renseignée.\n\n"
                    "Veux-tu utiliser Openverse (sans clé) à la place ?\n"
                    "(Oui = Openverse · Non = j'annule pour coller ma clé)"):
                return
            imgprov_var.set("openverse")

        persist()
        if key_var.get().strip():
            os.environ["ELEVENLABS_API_KEY"] = key_var.get().strip()
        if pix_var.get().strip():
            os.environ["PIXABAY_API_KEY"] = pix_var.get().strip()

        out_dir = Path(ep) / "output"
        state["out_dir"] = str(out_dir)
        el_voice = el_voice_map.get(el_voice_var.get(), el_voice_var.get()).strip()
        argv = [ep, "--tts", tts_var.get(), "--formats", fmt_var.get(),
                "--transition", trans_var.get(), "--voice", edge_voice_var.get(),
                "--se-voice", se_voice_var.get()]
        if el_voice:
            argv += ["--elevenlabs-voice", el_voice]
        if not intro_var.get():
            argv.append("--no-intro")
        if not motion_var.get():
            argv.append("--no-motion")
        if autoimg_var.get():
            argv += ["--auto-images", "--image-provider", imgprov_var.get()]

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

    def open_ai_dialog() -> None:
        provider = ai_prov_var.get()
        key = ai_key_var.get().strip()
        if not key:
            where = "console.groq.com (gratuit)" if provider == "groq" else "console.anthropic.com"
            messagebox.showinfo(APP_NAME, f"Colle d'abord ta clé {provider} — {where}.")
            return
        persist()
        from vpipeline import ai_script
        cfg = {"ai": {"provider": provider, "key": key}}
        conv: list[dict] = []
        busy = {"v": False}

        win = tk.Toplevel(root)
        win.title("Écrire un script avec l'IA")
        win.minsize(560, 560)
        if ico:
            try:
                win.iconbitmap(str(ico))
            except Exception:
                pass

        ttk.Label(win, text="Sujet / idée de la vidéo :").pack(anchor="w", padx=10, pady=(10, 0))
        topic_txt = tk.Text(win, height=3, wrap="word")
        topic_txt.pack(fill="x", padx=10)

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=10, pady=6)
        ttk.Label(bar, text="Segments :").pack(side="left")
        seg_var = tk.IntVar(value=5)
        ttk.Spinbox(bar, from_=2, to=20, width=5, textvariable=seg_var).pack(side="left", padx=6)
        gen_b = ttk.Button(bar, text="Générer le script")
        gen_b.pack(side="left", padx=6)
        status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=status, foreground="#888").pack(side="left", padx=6)

        ttk.Label(win, text="Script (modifiable) :").pack(anchor="w", padx=10)
        out_txt = tk.Text(win, height=16, wrap="word", bg="#101418",
                          fg="#e6e6e6", insertbackground="#e6e6e6")
        out_txt.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        ref = ttk.Frame(win)
        ref.pack(fill="x", padx=10, pady=4)
        ttk.Label(ref, text="Ajuster :").pack(side="left")
        refine_var = tk.StringVar()
        ref_entry = ttk.Entry(ref, textvariable=refine_var)
        ref_entry.pack(side="left", fill="x", expand=True, padx=6)
        ref_b = ttk.Button(ref, text="Affiner")
        ref_b.pack(side="left")

        bot = ttk.Frame(win)
        bot.pack(fill="x", padx=10, pady=(0, 10))
        make_b = ttk.Button(bot, text="✅ Créer l'épisode")
        make_b.pack(side="right")

        def set_out(t: str) -> None:
            out_txt.delete("1.0", "end")
            out_txt.insert("1.0", t)

        def set_busy(b: bool) -> None:
            busy["v"] = b
            for w in (gen_b, ref_b, make_b):
                w.config(state="disabled" if b else "normal")

        def run_ai(messages: list[dict]) -> None:
            if busy["v"]:
                return
            set_busy(True)
            status.set("… l'IA réfléchit")

            def worker() -> None:
                try:
                    text = ai_script.clean_script(ai_script.complete(messages, cfg, key))
                except Exception as exc:
                    win.after(0, lambda e=exc: (status.set("échec"), set_busy(False),
                                                messagebox.showerror(APP_NAME, f"Échec : {e}", parent=win)))
                    return

                def ok() -> None:
                    conv.append({"role": "assistant", "content": text})
                    set_out(text)
                    status.set("prêt")
                    set_busy(False)
                win.after(0, ok)
            threading.Thread(target=worker, daemon=True).start()

        def on_generate() -> None:
            topic = topic_txt.get("1.0", "end").strip()
            if not topic:
                messagebox.showinfo(APP_NAME, "Écris d'abord un sujet.", parent=win)
                return
            n = max(2, min(int(seg_var.get() or 5), 20))
            conv.clear()
            conv.append({"role": "user", "content":
                         f"Sujet de la vidéo : {topic}\n\nÉcris le script avec exactement "
                         f"{n} segments (en plus du titre). Narration concise pour une voix off."})
            run_ai(list(conv))

        def on_refine() -> None:
            instr = refine_var.get().strip()
            if not instr:
                return
            cur = out_txt.get("1.0", "end").strip()
            if conv and conv[-1]["role"] == "assistant":
                conv[-1]["content"] = cur
            elif cur:
                conv.append({"role": "assistant", "content": cur})
            conv.append({"role": "user", "content": instr})
            refine_var.set("")
            run_ai(list(conv))

        def on_make() -> None:
            text = out_txt.get("1.0", "end").strip()
            if not text:
                messagebox.showinfo(APP_NAME, "Génère d'abord un script.", parent=win)
                return
            parent = filedialog.askdirectory(title="Où créer l'épisode ?")
            if not parent:
                return
            import time
            name = (text.splitlines()[0].lstrip("# ").strip() or "episode")[:50]
            try:
                ep = create_episode(parent, name)
            except FileExistsError:
                ep = create_episode(parent, f"{name}-{int(time.time()) % 10000}")
            (ep / "script.md").write_text(ai_script.clean_script(text), encoding="utf-8")
            episode_var.set(str(ep))
            win.destroy()
            messagebox.showinfo(
                APP_NAME, f"Épisode créé :\n{ep}\n\n"
                f"Choisis la source d'images (ou laisse l'IA les créer), puis Générer.")

        gen_b.config(command=on_generate)
        ref_b.config(command=on_refine)
        make_b.config(command=on_make)

    claude_btn.config(command=open_ai_dialog)

    def on_close() -> None:
        persist()   # mémorise la clé et les réglages même sans génération
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    # Bilan de l'installation au démarrage (ffmpeg, etc.).
    try:
        import check_setup
        bootstrap_ffmpeg()
        checks = check_setup.run_checks()
        append("Vérification de l'installation :\n")
        for label, ok, hint in checks:
            append(f"   {'✓' if ok else '✗'}  {label}\n")
            if not ok and hint:
                append(f"        → {hint}\n")
        append("\n" + ("✅ Tout est prêt — choisis un épisode et clique Générer.\n"
                       if check_setup.all_essentials_ok(checks)
                       else "⚠ Un élément essentiel manque (voir les ✗ ci-dessus).\n"))
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    launch()
