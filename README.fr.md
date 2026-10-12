# Atelier

Français · [English](README.md)

Hub web local, tout-en-un et hors ligne après installation, pour la traduction, les médias et les
documents. Un petit service FastAPI sur `127.0.0.1:7777`, une UI HTML/JS vanilla (sans build ni CDN) et
une file de tâches qui enveloppe des CLI éprouvées au lieu de les réimplémenter.

Développé et testé sur **CachyOS / Arch Linux** avec un GPU AMD (RX 6900 XT, Vulkan). L'interface est en
français par défaut, avec une bascule vers l'anglais dans la barre latérale.

## Fonctionnalités

| Onglet | Contenu |
|---|---|
| **Traduire** | Texte libre, découpage par blocs avec contexte, flux en direct, glossaires, image → texte → traduction (modèle vision), dictée (micro → whisper.cpp), lecture à voix haute / export MP3 (Piper) |
| **YouTube** | Vidéo ou playlist → mkv / mp3 / sous-titres seuls, choix de qualité, progression réelle |
| **Sous-titres** | URL ou média/SRT local → sous-titres existants, sinon whisper.cpp → SRT traduit (+ mkv soft-sub), résumé du transcript avec chapitres horodatés |
| **Documents** | PDF (pdf2zh-next, mono + bilingue, OCR auto des scans), DOCX / PPTX / XLSX avec mise en forme inline conservée, EPUB (table des matières + métadonnées conservées) |
| **Convertir** | Vidéo/audio (ffmpeg, VAAPI h264/hevc, AV1 en CPU), images (libvips), documents (pandoc + LibreOffice), e-books (calibre), lot + zip |
| **Images** | Agrandissement ×2 / ×4 (Real-ESRGAN, Vulkan), détourage (rembg) |
| **Audio** | Séparation des pistes (Demucs), réduction du bruit de la voix (DeepFilterNet) |
| **Services** | Sonde, démarrage et arrêt de vos autres services locaux (Open WebUI, Jellyfin…) |
| **Système** | VRAM, modèles Ollama chargés, dépendances, espace disque et nettoyage |

En plus : verrou GPU global (une tâche GPU à la fois, modèles déchargés avant les jobs GPU hors Ollama),
file de tâches avec progression SSE, annulation, relance, journal par tâche, notifications de bureau,
fenêtre native optionnelle (pywebview) avec entrée de menu.

35 langues, avec les variantes expliquées (portugais PT/BR, chinois simplifié/traditionnel, philippin vs
cebuano, indonésien vs malais…).

## Prérequis

- Linux avec systemd (unités utilisateur), Python 3.12 + [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) avec un modèle de traduction (défaut `translategemma:12b`) et un second
  modèle (défaut `gemma3:12b`, résumés et traduction d'image)
- `ffmpeg`, `yt-dlp` ; whisper.cpp compilé avec Vulkan (`scripts/build-whisper.sh`)
- Selon les fonctions (le panneau **Système → Dépendances** indique ce qui manque et comment l'installer) :
  `pdf2zh-next`, `ocrmypdf` + `tesseract`, `pandoc`, LibreOffice, `calibre`, `libvips`, `piper-tts`,
  `rembg`, `realesrgan-ncnn-vulkan`, `demucs`, `deep-filter`

Atelier ne télécharge ni n'installe rien lui-même.

## Installation

```bash
git clone https://github.com/kerstz/atelier && cd atelier
bash scripts/env-check.sh          # ce qui est présent / manquant
uv sync --frozen
bash scripts/install-service.sh    # unité systemd --user, écoute sur 127.0.0.1:7777
bash scripts/install-desktop.sh    # optionnel : entrée de menu + fenêtre native
```

Ouvrir <http://127.0.0.1:7777>. Les réglages sont dans `config.toml` (modèles, chemins, ports, voix, limites).

## Tests

Pas de framework de test : un script smoke par phase.

```bash
bash scripts/smoke-all.sh --quick    # tout sauf les longs/réseau (3, 4, 5)
bash scripts/smoke-all.sh            # complet (Ollama, whisper.cpp, réseau)
```

## Sécurité

Mono-utilisateur, local uniquement : écoute sur loopback, refuse les en-têtes `Host`/`Origin` étrangers
(même origine seulement), ne construit jamais de commande shell depuis l'UI, écrit uniquement dans
`~/Atelier` et le dossier de données. Ne pas l'exposer sur un réseau.

## Licence

Non spécifiée pour l'instant.
