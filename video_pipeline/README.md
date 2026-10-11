# 🎬 video_pipeline — voix + images → vidéo

Mini pipeline Python pour produire une vidéo par épisode à partir d'un **script**
(lu par une voix de synthèse) et d'un **dossier d'images**. Pensé pour une
**chaîne** : tu le montes une fois, puis chaque épisode = un dossier + une commande.

```
un dossier d'épisode  (script.md + images/)   →   une commande   →   la vidéo (.mp4 + .srt)
```

- ✅ Zéro abonnement, zéro filigrane — c'est ton outil.
- ✅ Style constant automatique : intro, textes à l'écran, bandeau sources, logo.
- ✅ **Crossfade** (fondu enchaîné) entre les images + zoom doux.
- ✅ **Images de fin / gag** : un carton ou une image avec bruitage en deux lignes.
- ✅ Plusieurs formats d'un coup : YouTube 16:9 **et** Short 9:16.
- ✅ Sous-titres `.srt` générés automatiquement.
- ✅ Voix au choix : ElevenLabs (défaut), edge-tts (gratuit), Piper (hors-ligne).

---

## 1. Ce qu'il te faut sur ton PC

| Besoin                | Pourquoi                        | Comment l'installer |
|-----------------------|---------------------------------|---------------------|
| **Python 3.9+**       | lance le pipeline               | [python.org](https://www.python.org/downloads/) · Windows : coche « Add Python to PATH » |
| **ffmpeg** (+ffprobe) | fabrique la vidéo               | **Win** : `winget install Gyan.FFmpeg` · **macOS** : `brew install ffmpeg` · **Linux** : `sudo apt install ffmpeg` |
| **une clé ElevenLabs**| la voix (backend par défaut)    | compte sur [elevenlabs.io](https://elevenlabs.io) → *Profile → API Keys* |
| (une police `.ttf`)   | textes à l'écran                | déjà présente sur la plupart des PC ; sinon renseigne `font` |

Vérifie que ffmpeg répond : `ffmpeg -version`. S'il est introuvable, c'est
qu'il n'est pas dans le PATH (sur Windows, rouvre le terminal après l'install).

Puis, une seule fois :

```bash
cd video_pipeline
pip install -r requirements.txt
```

> Le pipeline tourne avec la **bibliothèque standard** de Python + ffmpeg.
> Les paquets de `requirements.txt` ne servent qu'à certaines options
> (voix `edge`, config YAML).

## 2. Lancer

**a) Essai sans rien configurer** (son silencieux, juste pour voir le montage) :

```bash
python make_video.py episodes/demo --tts dummy
# -> episodes/demo/output/openbuilds-cam-en-60-secondes__long.mp4  (+ .srt)
```

**b) Pour de vrai, avec la voix ElevenLabs** (backend par défaut). Mets d'abord
ta clé dans une variable d'environnement, puis lance :

```bash
# macOS / Linux
export ELEVENLABS_API_KEY="sk_ta_cle_ici"
python make_video.py episodes/demo

# Windows (PowerShell)
$env:ELEVENLABS_API_KEY="sk_ta_cle_ici"
python make_video.py episodes/demo
```

C'est tout : la vidéo (16:9 par défaut) et son `.srt` arrivent dans
`episodes/demo/output/`. Pour ton propre épisode, remplace `episodes/demo` par
le dossier de ton épisode (voir §3).

> Pas (encore) de clé ElevenLabs ? Utilise `--tts edge` (voix gratuite, §5) ou
> `--tts dummy` (silence, pour tester le montage).

## 3. Structure d'un épisode

```
episodes/
  mon-episode/
    script.md         # le texte (narration + directives)
    images/           # les images (jpg, png, webp…)
    assets/           # optionnel : bruitages, musique ([audio: assets/...])
    config.yaml       # optionnel : surcharge le style de la chaîne
    output/           # généré : les vidéos + sous-titres (ignoré par git)
```

Pour créer un nouvel épisode : copie `episodes/demo`, remplace le script et les
images, puis lance la commande.

## 4. Format du script

Un **segment** par bloc, séparé par une ligne vide. Les lignes `[clé: valeur]`
sont des **directives** ; tout le reste est le texte **lu par la voix**.

```markdown
# Titre de l'épisode                 <- sert à l'intro

[img: schema.png]                    <- image du segment (sinon auto depuis images/)
[text: Étape 1 : importer]           <- texte affiché à l'écran
[source: docs.openbuilds.com]        <- petit bandeau sources en bas
Voici la narration lue par la voix. Elle peut tenir
sur plusieurs lignes dans le même bloc.

[img: apercu.png]
Deuxième segment de narration…
```

Directives disponibles (toutes optionnelles sauf le texte) :

| Directive          | Effet |
|--------------------|-------|
| `[img: fichier]`   | image du segment (sinon, image suivante de `images/`) |
| `[text: …]`        | texte affiché à l'écran |
| `[source: …]`      | petit bandeau « Sources : … » en bas |
| `[audio: fichier]` | joue un **son** (bruitage, sting) au lieu de la voix |
| `[hold: N]`        | tient l'image **N secondes** (pour une image sans narration) |

Règles :
- **Pas de `[img:]` ?** Le pipeline pioche l'image suivante du dossier `images/`
  (ordre alphabétique). Nomme tes images `01_…`, `02_…` pour contrôler l'ordre.
- La durée de chaque image = la durée de sa narration (ou du son, ou du `hold`).

### Images de fin / gag 🎬

Un segment **sans narration** devient une image qu'on tient à l'écran — idéal
pour un gag de fin ou un carton de sortie. Deux variantes :

```markdown
// Gag : une image + un bruitage (sa durée = celle du son)
[img: oups.png]
[text: Bon… j'avais oublié de serrer la fraise.]
[audio: assets/pouet.wav]

// Carton de fin : une image tenue 3 secondes, en silence
[img: a_bientot.png]
[hold: 3]
```

Ces segments ne sont pas mis en sous-titres, et le crossfade s'applique
normalement avant/après. Mets autant de gags que tu veux, où tu veux.

## 5. Choisir la voix (TTS)

| Backend          | Qualité         | Hors-ligne | Mise en place                               |
|------------------|-----------------|:----------:|---------------------------------------------|
| **`elevenlabs`** | excellente      | non        | **défaut** — `export ELEVENLABS_API_KEY=…`  |
| `edge`           | très bonne      | non        | `pip install edge-tts` (gratuit)            |
| `piper`          | bonne (neuronal)| oui        | binaire `piper` + un modèle `.onnx`         |
| `espeak`         | robotique       | oui        | `apt install espeak-ng`                     |
| `dummy`          | silence         | oui        | rien — pour tester le montage               |

```bash
# ElevenLabs (défaut) — la plus naturelle
export ELEVENLABS_API_KEY=sk_...
python make_video.py episodes/mon-episode
# choisir la voix : dans la config -> tts.elevenlabs_voice_id: "ID_ou_nom"

# voix gratuite edge-tts (fr féminine ; fr-FR-HenriNeural pour une voix masculine)
python make_video.py episodes/mon-episode --tts edge --voice fr-FR-DeniseNeural
```

> 💡 Les voix sont **mises en cache** (`episodes/<ep>/.cache/`). Relancer après
> une modif ne re-synthétise que les segments dont le texte a changé.

## 6. Options de la commande

```bash
python make_video.py <dossier-épisode> [options]

  --config FICHIER     config de style (.yaml ou .json)
  --formats long,short formats à produire (long | short | square | 1280x720)
  --tts BACKEND        elevenlabs | edge | piper | espeak | dummy
  --voice VOIX         ex: fr-FR-DeniseNeural (backend edge)
  --transition T       crossfade (défaut) | fade
  --no-intro           désactive l'intro
  --no-motion          désactive le zoom (effet Ken Burns) sur les images
  --out DOSSIER        dossier de sortie (défaut: <épisode>/output)
  --keep-temp          garde les fichiers intermédiaires (debug)
```

## 7. Style de la chaîne (réutilisable)

Copie [`config.example.yaml`](config.example.yaml) en `channel.yaml`, règle-le
une fois (logo, police, couleurs, intro, musique), puis branche-le sur chaque
épisode :

```bash
python make_video.py episodes/ep01 --config channel.yaml
python make_video.py episodes/ep02 --config channel.yaml   # même style
```

Ou dépose un `config.yaml` dans le dossier de l'épisode : il est pris
automatiquement. Un épisode peut ainsi surcharger ponctuellement le style global.

Points de style les plus utiles : `logo.path`, `font`, `captions`,
`source_banner`, `intro`, `music.path`. Tout est documenté dans
`config.example.yaml`.

## 8. Comment ça marche (sous le capot)

1. **Voix** : chaque segment est synthétisé en WAV (une seule fois, mis en cache).
2. **Clips** : chaque image devient un clip d'un nombre **entier** de frames ;
   son audio est calé **exactement** sur cette durée → aucune dérive A/V.
3. **Montage** : en `crossfade`, les clips sont enchaînés en fondu (`xfade`,
   chaque clip rendu un poil plus long pour alimenter le recouvrement, si bien
   que la durée totale reste égale à l'audio) ; en `fade`, ils sont concaténés
   sans ré-encodage. La voix est concaténée, la musique mixée en dessous.
4. **Sortie** : muxage `.mp4` (H.264/AAC, `+faststart`) + sous-titres `.srt`.

Le même audio sert pour tous les formats : produire `long` + `short` ne
re-synthétise pas la voix.

## 9. Dépannage

- **`'ffmpeg' introuvable`** → installe ffmpeg et vérifie qu'il est dans le PATH.
- **Textes à l'écran absents** → aucune police `.ttf` trouvée ; renseigne `font`
  dans la config (chemin d'un `.ttf`).
- **edge-tts échoue** → pas de réseau ou voix invalide ; teste avec `--tts dummy`.
- **Config YAML refusée** → `pip install pyyaml`, ou utilise un fichier `.json`.

---

Fait partie du dépôt OpenBuilds-CAM, mais **totalement autonome** : ce dossier
ne dépend de rien d'autre dans le repo.
