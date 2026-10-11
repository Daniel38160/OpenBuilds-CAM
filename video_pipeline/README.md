# 🎬 video_pipeline — voix + images → vidéo

Mini pipeline Python pour produire une vidéo par épisode à partir d'un **script**
(lu par une voix de synthèse) et d'un **dossier d'images**. Pensé pour une
**chaîne** : tu le montes une fois, puis chaque épisode = un dossier + une commande.

```
un dossier d'épisode  (script.md + images/)   →   une commande   →   la vidéo (.mp4 + .srt)
```

- ✅ Zéro abonnement, zéro filigrane — c'est ton outil.
- ✅ Style constant automatique : intro, textes à l'écran, bandeau sources, logo.
- ✅ Plusieurs formats d'un coup : YouTube 16:9 **et** Short 9:16.
- ✅ Sous-titres `.srt` générés automatiquement.
- ✅ Voix au choix : edge-tts (gratuit), Piper (hors-ligne), ElevenLabs (API).

---

## 1. Installation

Prérequis : **Python 3.9+** et **ffmpeg** (avec `ffprobe`).

```bash
# ffmpeg (Debian/Ubuntu)
sudo apt install ffmpeg

# dépendances Python (optionnelles selon les options voulues)
cd video_pipeline
pip install -r requirements.txt
```

> Le pipeline fonctionne avec la **bibliothèque standard** de Python + ffmpeg.
> `edge-tts` (voix gratuite) et `PyYAML` (config YAML) ne sont nécessaires que
> pour ces options précises.

## 2. Essai immédiat (sans réseau)

```bash
python make_video.py episodes/demo --tts dummy
# -> episodes/demo/output/openbuilds-cam-en-60-secondes__long.mp4  (+ .srt)
```

`--tts dummy` produit un **son silencieux** calibré sur la durée du texte :
parfait pour valider le montage sans dépendre d'internet. Pour une vraie voix,
voir §5.

## 3. Structure d'un épisode

```
episodes/
  mon-episode/
    script.md         # le texte (narration + directives)
    images/           # les images (jpg, png, webp…)
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

Règles :
- **Pas de `[img:]` ?** Le pipeline pioche l'image suivante du dossier `images/`
  (ordre alphabétique). Nomme tes images `01_…`, `02_…` pour contrôler l'ordre.
- `[text:]`, `[source:]` sont facultatifs.
- La durée de chaque image = la durée de la narration de son segment.

## 5. Choisir la voix (TTS)

| Backend      | Qualité        | Hors-ligne | Mise en place                                   |
|--------------|----------------|:----------:|-------------------------------------------------|
| `edge`       | très bonne     | non        | `pip install edge-tts` (par défaut)             |
| `piper`      | bonne (neuronal)| oui       | binaire `piper` + un modèle `.onnx`             |
| `elevenlabs` | excellente     | non        | `export ELEVENLABS_API_KEY=...`                 |
| `espeak`     | robotique      | oui        | `apt install espeak-ng`                         |
| `dummy`      | silence        | oui        | rien — pour tester le montage                   |

```bash
# voix gratuite edge-tts (féminine fr par défaut)
python make_video.py episodes/mon-episode

# voix masculine, un peu plus rapide
python make_video.py episodes/mon-episode --voice fr-FR-HenriNeural

# ElevenLabs
export ELEVENLABS_API_KEY=sk_...
python make_video.py episodes/mon-episode --tts elevenlabs
```

> 💡 Les voix sont **mises en cache** (`episodes/<ep>/.cache/`). Relancer après
> une modif ne re-synthétise que les segments dont le texte a changé.

## 6. Options de la commande

```bash
python make_video.py <dossier-épisode> [options]

  --config FICHIER     config de style (.yaml ou .json)
  --formats long,short formats à produire (long | short | square | 1280x720)
  --tts BACKEND        edge | piper | elevenlabs | espeak | dummy
  --voice VOIX         ex: fr-FR-DeniseNeural
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
3. **Montage** : les clips (codec/résolution/fps identiques) sont concaténés sans
   ré-encodage, la voix est concaténée, la musique est mixée en dessous.
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
