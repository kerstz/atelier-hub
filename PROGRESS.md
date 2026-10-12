# PROGRESS

## Phase 1 — skeleton
done: CLAUDE.md, config.toml, atelier/{config,db,proc,jobs,gpu,ollama,main}.py, static UI (6 onglets, Système actif), scripts/{env-check,smoke,install-service}.sh, systemd/atelier.service.
decisions:
- host 127.0.0.1 en dur (non configurable); middleware refuse Host/Origin non-locaux.
- job kinds via jobs.register(name, handler, gpu=bool|fn(params)); handler(ctx, params) -> output path|None. `demo` kind = test.
- GPU lock = asyncio.Lock FIFO; job GPU "En file" tant que verrou pris. Non-GPU: immédiat.
- run_cmd (proc.py): killpg sur cancel, erreur = 3 dernières lignes.
- au démarrage: jobs queued/running -> failed "interrompu".
- unit systemd: `uv run --frozen --offline python -m atelier`, WorkingDirectory = repo.
env: python système 3.14.7 (uv fournira 3.12); uv, yt-dlp, ffmpeg OK; ollama + whisper.cpp absents; card1 expose mem_info_vram_*.
env non vérifié: tag exact `translategemma:12b` (ollama absent), fallback gemma3:12b.
next: phase 2 Traduire.

## Phase 2 — Traduire (code écrit, non lancé)
done: translate.py (prompt, chunk, stream /api/chat), job kind `translate` (gpu), SSE event `delta`, table translations (20 max), UI onglet Traduire (glossaire, swap, copier, historique), scripts/smoke2.sh.
env: ollama OK, `translategemma:12b` pull OK, `ollama ps` = 100% GPU, ctx 4096 par défaut. Tag config.toml inchangé.
decisions:
- traduction = job GPU (file + annuler gratuits); tokens poussés en SSE `delta` {id,text}, UI bufferise par id.
- prompt officiel TranslateGemma; src=auto -> variante sans langue source. Glossaire: seuls termes présents dans le bloc, injectés avant le texte. temperature 0.
- chunk: paragraphes, repli phrases, limite translate.chunk_chars=2500 (marge vs ctx 4096).
- historique sauvé seulement si job terminé; langs/glossaire en localStorage.
next: phase 3 YouTube.
fix (post-run): db.update sans champs -> syntaxe sqlite 500 au submit; smoke*.sh attendent le serveur (race restart). smoke.sh + smoke2.sh = ok.

## Phase 3 — YouTube (smoke3.sh ok, réseau inclus)
done: youtube.py (probe -J --flat-playlist, job `youtube` non-GPU, Tracker progression), POST /api/youtube/probe, UI onglet YouTube (analyse, mode, qualité, langues, playlist), scripts/smoke3.sh, config [youtube].
decisions:
- modes: video `bv*[height<=Q]+ba/...` -> mkv + metadata/chapters; audio mp3 q0 + thumbnail jpg; subs `--write-subs --write-auto-subs --convert-subs srt` (langs défaut "en", pas "en,fr": évite 429 auto-traduction).
- fichiers `-P ~/Atelier/youtube -o "%(title).120B.%(ext)s"`; playlist -> `%(playlist_title).80B/%(playlist_index)02d - ...`; `--windows-filenames` garde accents. Playlist décidée côté serveur via probe, pas confiance UI.
- progression: % par flux (video=2 flux) / item / total; clamp 0.99 jusqu'à fin job.
- playlist rc=1 avec ≥1 fichier et erreurs -> job "done" + message "terminé avec N erreur(s)".
- URL: http(s) seulement, `--` avant URL; qualité/langs validées regex.
- `store` (localStorage) global dans app.js.
env: yt-dlp 2026.08.19, deno présent (runtime JS par défaut OK). Sorties test: ~/Atelier/youtube.
next: phase 4 Sous-titres (whisper.cpp absent: voir env-check).
env (avant phase 4): pas de yay/paru; repos n'ont que `whisper-cpp` 1.9.4 (CPU, sans Vulkan) -> build source via scripts/build-whisper.sh (cmake -DGGML_VULKAN=1, cmake/glslc/vulkan-headers présents), bin symlink ~/.local/bin/whisper-cli, modèle ~/.local/opt/whisper.cpp/models/ggml-large-v3-turbo.bin.

## Phase 4 — Sous-titres (smoke4.sh ok)
done: srt.py (parse/build/wrap), subs.py (job `subtitles`), translate.complete, POST /api/upload (uploads/ purgé à 2 j, + supprimé après job), UI onglet Sous-titres (URL/chemin/fichier/drag&drop), scripts/smoke4.sh, config [whisper] [subtitles].
env: whisper-cli v1.9.4 Vulkan (source, ~/.local/opt/whisper.cpp), large-v3-turbo 1.6 Go; 19 s audio ≈ 2 s sur 6900 XT.
decisions:
- pipeline: URL -> yt-dlp sous-titres manuels `<src>.*` (auto-captions off, cfg) -> sinon bestaudio -> ffmpeg 16k mono -> whisper -osrt -pp. Local .srt direct.
- LLM voit `[n] texte` aplati (tags retirés); timestamps jamais envoyés; re-wrap 42 car / 2 lignes en sortie.
- lot 40 cues; contexte = lot précédent en tours chat user/assistant (prompt officiel conservé); num_ctx 8192 (peut recharger le modèle une fois).
- validation: ids exacts et ordonnés; échec -> retry temp 0.4 -> bisection -> cue seule sans numéro -> sinon texte source.
- cues sans lettre/chiffre (♪) non envoyées.
- verrou GPU pris par étape (whisper, traduction), pas pendant téléchargement/mux; job non-GPU côté manager.
- sorties ~/Atelier/subs: `<nom>.<src>.srt`, `<nom>.<tgt>.srt`, optionnel `<nom>.<tgt>.mkv` (soft-sub, langue iso3 + titre, disposition default; original intact).
- mux ignoré si entrée audio seule.
next: phase 5 Documents (pdf2zh-next absent: `uv tool install --python 3.12 pdf2zh-next`).

## Phase 5 — Documents (smoke5.sh ok)
done: docs.py (job `document`), batch.py (Translator extrait de subs.py, partagé), proc.run_cmd split \r+\n, UI onglet Documents (drag&drop multi, pages PDF, glossaire), scripts/smoke5.sh, config [docs]; deps uv: python-docx, python-pptx, openpyxl.
env: pdf2zh_next 2.9.0 via uv tool; FIX requis après install/upgrade: `scripts/fix-pdf2zh.sh` (idempotent, bitstring<5; bitstring 5 casse babeldoc).
decisions:
- PDF: CLI `pdf2zh_next --ollama` modèle = docs.pdf_model || translate_model (translategemma:12b OK sur test), verrou GPU tout le run, sorties `<nom>.<tgt>.mono.pdf` + `.dual.pdf` (infixe .no_watermark retiré), glossaire -> CSV --glossaries, auto-glossaire off.
- Office: paragraphes/cellules, texte en 1er run/w:t, autres vidés: formatage mixte (gras partiel) s'écrase au 1er run. Tables, en-têtes/pieds, notes, groupes pptx, cellules xlsx (nombres/formules intacts). Doublons dédupliqués, lots 40/2500 car.
- xlsx: graphiques/images perdus (limite openpyxl).
- PDF progression: pas de % exploitable (barre rich non-tty): barre à 0 puis done.
next: phase 6 Services.

## Phase 6 — Services (smoke6.sh ok)
done: services.py, GET /api/services (sonde TCP 127.0.0.1), POST /api/services/{id}/{start|stop}, UI onglet Services (pastille, Ouvrir, Démarrer/Arrêter, poll 5 s), scripts/smoke6.sh, config [services.*].
decisions:
- config: `[services.<id>] name, port, url?, unit?` (systemctl --user) ou `dir?, file?` (docker compose). Sans unit/dir: sonde + lien seulement.
- seuls les ids du config.toml sont pilotables; commandes jamais construites depuis l'entrée UI.
- compose: start = `up -d --pull never` (aucun téléchargement), stop = `stop`. Timeout 120 s.
- smoke6 ne démarre/arrête rien (ne touche pas aux vrais services).
env: aucun service n'a unit/dir dans config.toml: à remplir par l'utilisateur pour activer Démarrer/Arrêter. Ports défauts: openwebui 3000, pinchflat 8945, jellyfin 8096, immich 2283, stirling 8080.
next: fin du plan. scripts/fix-pdf2zh.sh à relancer après `uv tool upgrade`.

## Phase 7 — Finition (smoke7.sh: partie hors-ligne ok, live à lancer)
done: inline.py (balises <b>/<i>/<aN> encode/decode), office.py (loaders docx/pptx/xlsx extraits de docs.py, Slot), docs.py (flux tagué + repli), progression PDF, scripts/smoke7.sh.
decisions:
- Office: paragraphe envoyé tagué seulement s'il a ≥2 formats (gras/italique/lien); sinon texte plat comme avant. Balises invalides/inconnues/non fermées -> relance du paragraphe en texte plat (ancien comportement, 1er run).
- docx: runs clonés depuis le run modèle (même format, sinon même lien), hyperlinks directs clonés. Champs (fldChar/fldSimple), runs avec tab/br/image, hyperlinks imbriqués -> chemin plat. pptx: a:br/a:fld -> plat. xlsx inchangé.
- PDF: pdf2zh-next dessine une barre rich; env FORCE_COLOR=1 TERM=xterm COLUMNS=160 pour qu'elle sorte hors tty, parse `translate ━━ n/100` (global) + ligne d'étape en message. Si rich ne rend pas: ancien comportement (0 puis done).
- Sous-titres -l: déjà en place depuis phase 4 (select Langue source -> whisper -l ; "Détecter" = auto). Rien changé, test ajouté dans smoke7. Défaut UI = en.
env: smoke7 live = Ollama + service up; vérifie progression PDF 0<max<1.
next: lancer scripts/smoke7.sh; si progression PDF reste 0, coller la sortie brute de `pdf2zh_next` (tty forcé) pour ajuster BAR_RE.

## Phase 8 — Refonte UI (smoke, smoke2, smoke6, smoke7 ok; smoke3/4/5 non relancés)
done: static/{ui.js,icons.svg,index.html,style.css} réécrits; app.js (shell, tray, toasts, thème, raccourcis); translate/youtube/subs/docs/services.js adaptés. Backend inchangé (sauf fix BAR_RE phase 7).
decisions:
- Composants dans ui.js: icon(sprite), button, card, toast, modal, progress, empty, skeleton, copy, select, segmented, dropzone(drag/coller/clic), chips. jobCard/jobsView dans app.js (tray + carte Résultat par onglet).
- Thème: :root sombre par défaut, clair via prefers-color-scheme ou data-theme (localStorage `theme`, try/catch). Bouton violet #6b47ff (AA avec texte blanc), accent #7c5cff pour focus/barres.
- Raccourcis: Ctrl+Entrée = bouton [data-main] de l'onglet, Ctrl+1..6 onglets, Échap ferme modal puis tray. Sidebar repliable (localStorage `sb`).
- Tray: s'ouvre à chaque nouveau job; toasts sur fin/échec de job observé en direct.
- icons.svg: 34 symboles Lucide (ISC), pas de CDN.
env: capture sombre Firefox: profil avec `ui.systemUsesDarkTheme=1` + `--no-remote`. Service à redémarrer après maj backend (`systemctl --user restart atelier`).
next: smoke3/4/5 non relancés (réseau YouTube / whisper / PDF), UI seule touchée.

## Phase 9 — OCR, résumé, image (smoke9.sh: hors-ligne + OCR ok; résumé/image skip faute de gemma3:12b)
done: ocr.py (has_text via pdftotext, ocr_pdf, job `ocr`), OCR auto dans do_pdf, summary.py (job `summary`, map-reduce), subs.acquire (extrait de subs.run), translate image (job translate + params.image), GET /api/jobs/{id}/result, UI: Résumer (YouTube, Sous-titres), OCR seul + options (Documents), dropzone image (Traduire).
decisions:
- ocrmypdf absent des dépôts pacman/CachyOS -> `uv tool install ocrmypdf` (PyPI 17.13.0, flags vérifiés via uvx). Auto-OCR si <50 car. alnum sur 5 premières pages; `-s -r -O 0 --output-type pdf`; `-f` si "refaire".
- Résumé: modèle = summary.model ou ollama.second_model; num_ctx [summary]; chunks (num_ctx-2400)*3 car.; notes par bloc, réduction récursive (≤4 niveaux), final streamé. Sortie ~/Atelier/subs/<nom>.resume.md + SRT copié (réutilisable sans whisper). URL sans sous-titres = whisper à chaque Résumer.
- Image: un seul appel vision (lit + traduit), `[ollama] vision_model`; `ollama.exclusive()` décharge les autres modèles (aussi avant résumé). Historique: source "[image] nom".
env: tesseract + data fra/eng/osd ok, pdftotext ok. Manque: ocrmypdf, gemma3:12b.
next: installer, relancer smoke9.sh (live), `systemctl --user restart atelier`.

## Phase 10 — Convertir + EPUB (smoke10.sh: hors-ligne ok; live à lancer après restart)
done: convert.py (job `convert`, détection, ffmpeg VAAPI/CPU, vips, pandoc/LibreOffice, calibre), epub.py (traduction XHTML/NCX/OPF), onglet Convertir (convert.js), endpoints catalog/detect/jobs/{id}/download/convert/zip, config [convert].
decisions:
- 1 job par fichier; zip = GET /api/convert/zip?ids= (jobs done du dernier lot). Sorties ~/Atelier/convert, noms uniques "(2)".
- Vidéo: h264/hevc VAAPI (-qp 20/25/30), repli CPU x264/x265 si échec; AV1 = libsvtav1 CPU. Même extension autorisée pour média (ré-encode/redim.), pas pour docs/ebooks. Verrou GPU seulement pour cibles VAAPI; CPU limité par [convert] jobs=2.
- Docs: pandoc si dispo, LibreOffice sinon, chaîne via docx temporaire (md→pdf). pandoc/calibre absents -> erreur avec commande pacman.
- EPUB: runs inline (b/i/liens=<aN>, code/img/br/notes sans lettres = atomes ⟦n⟧ re-posés tels quels, pre/script ignorés). Échec balises -> texte plat + atomes. TOC nav+NCX traduits, OPF: titre/description traduits, langue=cible, reste intact. Span imbriqué: wrapper externe retiré.
env: pandoc, calibre absents (sudo pacman -S pandoc-cli calibre). Restart: `systemctl --user restart atelier`.
next: phase 11 (à définir), puis phase 12 (appli desktop, spec fournie par l'utilisateur), puis gros audit avec Opus 5.5.

## Phase 11 — TTS, dictée, Images, Audio (smoke11.sh: plomberie hors-ligne ok avec faux binaires; modèles réels non testés)
done: speech.py (jobs tts + dictate), images.py (upscale/rembg), audio.py (demucs/deep-filter), util.py, onglets Images + Audio (media.js), Traduire: Dicter / Écouter / MP3, icônes mic/volume/image/music, config [tts] [images] [audio].
decisions:
- Piper: texte via stdin, `-m <voices_dir>/<voix>.onnx -f out.wav`. Voix par langue (défauts fr/en/de/es/it, surcharge [tts.voices]). Écouter = wav ~/Atelier/audio/.listen/<id>.wav (purgé >1 j au démarrage), MP3 = ~/Atelier/audio/*.mp3.
- Dictée: MediaRecorder -> upload -> job dictate (whisper-cli -nt, verrou GPU) -> texte renvoyé par event delta (non persisté), ajouté à #tr-in. Langue = source (auto ok). Max 5 min.
- Upscale: realesrgan-x4plus (photo) / x4plus-anime, toujours x4 puis vips resize 0.5 pour ×2; plafond 24 MP en entrée. Sortie png. Verrou GPU. rembg: CPU, modèles u2net/isnet-general-use/u2net_human_seg/isnet-anime.
- Audio: demucs htdemucs (4 pistes ou --two-stems vocals), entrée convertie wav 44.1k stéréo, sortie dossier "<nom> (pistes)"; deep-filter sur wav 48k mono. CPU lourd en série (Semaphore HEAVY). demucs_device auto => verrou GPU.
- Bouton Télécharger de la tray: affiché pour toute sortie fichier (extension), sauf youtube.
env: piper 1.8.0 (+voix fr_FR-siwis-medium) et rembg installés, flags piper vérifiés réel. realesrgan (~/.local/opt/realesrgan, testé RX 6900 XT) et deep-filter (~/.local/bin) installés, flags vérifiés réel. rembg: modèle u2net à télécharger au 1er usage.
next: installer + `systemctl --user restart atelier` + smoke11; phase 12 (desktop) puis audit Opus 5.5.

## Phase 12 — Appli desktop (smoke12.sh ok; fenêtre testée en réel sous Hyprland)
done: scripts/atelier-desktop (lanceur), scripts/atelier_desktop.py (pywebview), static/icon.svg, desktop/atelier.desktop.in, install-desktop.sh / uninstall-desktop.sh, notify.py (notify-send fin de job), hash #onglet?text=/url= (app.js route + prefill translate/youtube), [desktop] notify/notify_min_seconds, groupe uv "desktop".
decisions:
- venv dédié ~/.local/share/atelier/desktop-venv: python système + --system-site-packages (gi/WebKitGTK/PyQt6 de pacman, pas de build PyGObject) + pywebview du groupe "desktop" (uv pip install --group). Le venv projet (py3.12) n'a pas gi.
- KDE|plasma -> gui=qt (qtpy + PyQt6; python-pyqt6-webengine requis, non testé), sinon gtk. Classe réelle relevée: `atelier` (hyprctl) = StartupWMClass; forcée par sys.argv[0] + GLib.set_prgname.
- Instance unique: flock sur $XDG_RUNTIME_DIR/atelier-desktop.lock puis focus via socket unix de la fenêtre (restore/show/present + hash) et hyprctl/swaymsg/kdotool/wmctrl en renfort.
- Repli: pywebview rc≠0 en <10 s ou venv absent -> chromium --app (profil dédié, --class=atelier), sinon firefox --new-window. --browser le force.
- Fenêtre = client pur: fermer n'arrête jamais le service. Service absent: systemctl --user start, attente 15 s, sinon notify-send critique.
- Presse-papiers: wl-paste (Wayland) puis xclip; texte coupé à 4000 car.; action "télécharger" exige http(s)://, onglet préremplit sans lancer.
- Notifs: jobs ≥5 s ou échecs; silence pour demo, dictate, tts écoute. Taille mémorisée dans ~/.config/atelier/window.json (position utile seulement en X11; Hyprland tile la fenêtre).
env: `bash scripts/install-desktop.sh` fait (venv + menu). Redémarrer le service pour activer les notifs: `systemctl --user restart atelier`. desktop-file-validate: seulement un hint (3 catégories principales, voulu).
next: audit Opus 5.5.

## Phase 13 — Fiabilité du cœur des jobs (smoke13.sh + smoke-all.sh)
done: joblog.py (journal par job), relance (POST /api/jobs/{id}/retry + bouton), upload consommé seulement à la réussite (jobs.py, plus dans les handlers), libération VRAM avant jobs GPU hors Ollama, scripts/smoke-all.sh, uv.lock à jour (groupe desktop).
decisions:
- Journal: contextvar joblog.JOB posé dans Manager._run (hérité par les sous-tâches); proc.run_cmd écrit `$ cmd`, chaque ligne (ANSI retiré) et `[code N]` dans data/logs/<id>.log; plafond 2 Mo puis marqueur + 15 dernières lignes (500 car. max). Traceback ajoutée à l'échec. Purge >14 j au démarrage; "Vider" supprime aussi les journaux. GET /api/jobs/{id}/log (300 Ko de fin), bouton Journal sur toute carte terminée (ui.viewer).
- Relance: failed/cancelled seulement; params relus en base; 410 si un upload référencé a disparu (uploads gardés 2 j par le purge de démarrage). Y compris "interrompu" au redémarrage.
- Uploads: util.consume_uploads(params) = toute valeur de params sous data/uploads, appelée après succès. translate image ne supprime plus après lecture.
- VRAM: Kind.frees_vram (dictate, image, audio) -> ollama.unload_all() sous le verrou GPU, + avant whisper-cli dans subs.transcribe. Coupé par [gpu] free_vram=false. Coût: le modèle Ollama se recharge à la tâche suivante.
- smoke-all.sh [--quick] [N…]: résumé ok/FAIL/skip/temps par script, code retour ≠0 si FAIL; --quick saute 3/4/5 (YouTube, whisper, PDF).
env: redémarrer le service pour les endpoints (`systemctl --user restart atelier`). smoke3/4/5 jamais relancés depuis phase 8: `bash scripts/smoke-all.sh` complet à lancer par l'utilisateur.
next: audit Opus 5.5; après audit: dépendances (panneau Système), contexte inter-blocs Traduire, glossaires serveur, chaînage d'outils, disque, a11y.

## Phase 14 — Correctifs audit, lots 1+2 (smoke14.sh)
done: H3+B3 (middleware origine complète + Sec-Fetch-Site), M3 (upload_paths résolu, clés path/image/source), H1 (upload gardé tant qu'un autre job actif le lit; keep_uploads pour subtitles/summary), M6 (pandoc), H2 (arrêt propre), M10 (purge périodique), B2 (kill enfant), M4 (profil soffice).
decisions:
- Middleware: Origin doit valoir http://<Host de la requête> (port compris). Sur /api/*, Sec-Fetch-Site ∉ {same-origin, none} -> 403 (couvre aussi autre port local = same-site). Pages statiques accessibles par lien. Sans header (curl, scripts) accepté.
- Uploads: consommés après succès sauf si un job queued/running les référence (db.active_params). subtitles/summary: jamais consommés (l'UI réutilise le fichier pour Résumer/Générer), purge par âge.
- Pandoc: `--sandbox` seul casse docx/odt/epub (data files introuvables). Deux étapes: lecteur --sandbox -> JSON AST, écrivain avec strip_images.lua (images -> texte alt). Testé en réel: aucun média embarqué. Bonus: chemins pandoc de smoke10 enfin exécutés (md->docx, md->pdf ok).
- Arrêt: uvicorn timeout_graceful_shutdown=3 + lifespan annule les jobs et attend 8 s (finally exécutés; jobs "cancelled", relançables). data/tmp vidé au démarrage; janitor horaire: uploads >2 j (sauf jobs actifs), .listen, journaux.
- proc.run_cmd: toute exception (callback, log) tue le groupe de processus enfant.
env: redémarrer le service (`systemctl --user restart atelier`) pour activer; le smoke14 live échoue avant restart.
next: lots 3 (SSE/UI: M1, M2), 4 (perf: M8, M9, M5), 5 (M7, B1, B4-B9) de l'audit.

## Phase 15 — Correctifs audit, lots 3+4 (smoke15.sh)
done: M1 (SSE saturée -> flux terminé + resync à l'ouverture), M2 (settle après lancement), M8 (progression coalescée, WAL, tray par carte), M9 (Office/EPUB hors boucle), M5 (slot CPU avant verrou GPU).
decisions:
- Manager.update: messages/progress seuls limités à 4/s par job avec flush différé (call_later 0.25 s); tout changement de statut passe tout de suite et emporte les champs en attente. SQLite: journal WAL + synchronous=NORMAL.
- SSE: file pleine -> abonné dans manager.dropped, générateur sort, EventSource se reconnecte, app.js `resync()` recharge /api/jobs et rejoue en événements "job" ceux qui ont changé (finit aussi les jobs restés "En cours" après redémarrage).
- UI: tray = une carte remplacée par événement (upsertJob), jobsView ne se redessine que pour les jobs de son filtre. settle(id) applique l'état final si l'événement a battu la réponse du POST.
- docs/epub: load, apply/rebuild, save/zip dans asyncio.to_thread (DOCX 6000 par., EPUB 250 chap.: pas de gel > 0.05 s). Upload: écriture disque via to_thread. EPUB: zip fermé dans finally (B6 partiel).
- GPU: convert (VAAPI) et audio (demucs GPU) ne passent plus gpu=True au gestionnaire: slot CPU (_sem / HEAVY) d'abord, puis gpu_lock dans le handler; demucs décharge Ollama lui-même.
env: redémarrer le service. smoke-all inclut maintenant 14 et 15.
next: lot 5 de l'audit: M7 (segments longs), B1 (taille upload/disque), B4 (timeout Ollama), B5 (notify --), B6 (plafond EPUB), B7 (socket /tmp), B8 (unique sorties), B9 (lxml, fastapi).

## Phase 16 — Correctifs audit, lot 5 (smoke16.sh)
done: M7 segments longs découpés, B1 limites d'upload, B4 timeout Ollama, B5 `--` notify-send, B6 plafonds EPUB, B7 dossier privé + port depuis config.toml, B8 noms de sortie uniques, B9 lxml/fastapi déclarés (uv.lock à jour).
decisions:
- translate_texts: tout segment > [translate] chunk_chars est découpé (translate.chunk) puis rejoint par espace; pièces dédoublonnées.
- Upload: [server] max_upload_mb=16384, min_free_gb=2; 413 (taille, Content-Length ou flux), 507 (disque, revérifié tous les 64 Mo); fichier partiel supprimé sur toute exception.
- Ollama: [ollama] timeout=300 s entre octets (chargement modèle compris) -> "Ollama ne répond plus".
- EPUB: total ≤3 Go, entrée parsée ≤64 Mo, ratio >200 au-dessus de 8 Mo refusé; zip fermé en cas d'erreur.
- Lanceur/fenêtre: socket + lock dans $XDG_RUNTIME_DIR sinon ~/.cache/atelier (0700), jamais /tmp; boucle de contrôle ne meurt plus sur client invalide.
- Sorties: free_base() choisit "<nom> (2)" si une sortie du lot existe déjà (subs: .srt/.mkv; docs: <nom>.<tgt>.*; ocr; résumé).
env: redémarrer le service. smoke-all (quick): 246 ok, 0 FAIL.
next: audit entièrement traité. Idées post-audit: panneau Dépendances, contexte inter-blocs Traduire, glossaires serveur, chaînage d'outils, disque, a11y. Demande en cours: langues supplémentaires (philippin).

## Phase 17 — Langues supplémentaires + explications des variantes (smoke17.sh)
done: 16 langues ajoutées (fil, ceb, pt-BR, zh-TW, id, ms, th, he, fa, bn, el, ro, hu, bg, da, fi), META par langue (whisper, iso3, yt-dlp, family, note), ui.langPicker (explication sous les sélecteurs Traduire / Sous-titres / Documents).
decisions (analyse Opus, lecture seule):
- LANGS reste (EN, FR); détails dans translate.META: whisper_code() ("auto" si pas de modèle Whisper: ceb), iso3(), sub_langs() (fil -> `fil.*,tl.*`, he -> `he.*,iw.*`, pt-BR/zh-TW avec repli sur la langue de base). ISO3 de subs.py supprimé.
- Philippin = deux langues distinctes: fil (langue nationale, base tagalog, dictée via -l tl) et ceb (Visayas/Mindanao, non intelligible avec fil, traduction expérimentale, dictée en auto).
- Variantes affichées côte à côte avec note de différence: pt/pt-BR, zh (simplifié)/zh-TW (traditionnel), fil/ceb, id/ms; RTL signalé pour ar/he/fa. `/api/langs` expose note + variants.
- Noms FR existants précisés: pt "portugais (Portugal)", zh "chinois simplifié". Langue pt-BR/zh-TW: prompt "Brazilian Portuguese (pt-BR)" / "Traditional Chinese (zh-TW)".
risques non vérifiés (pas de réseau/modèle): codes attendus par translategemma pour fil/pt-BR/zh-TW (tester "Filipino (fil)" vs "Tagalog (tl)" sur 2-3 phrases), qualité ceb/ms, chunk() sur le thaï (pas de ponctuation .!?), PDF droite-gauche dégradé, OCR: tesseract-data seulement fra+eng (ocr_langs global).
env: redémarrer le service. Voix Piper: aucune par défaut pour ces langues (ajouter [tts.voices]).

## Correctifs suite à smoke-all complet (2026-10-12)
- smoke4: "upload supprimé" obsolète depuis phase 14 (subtitles keep_uploads) -> test attend maintenant l'upload conservé.
- smoke5 (vrai bug phase 16): le nom unique de docs.run comparait tous les formats (`<nom>.<tgt>.*`): un pptx du même nom qu'un docx existant devenait "<nom> (2)". Corrigé: docs.output_base compare par type de sortie (docx/pptx/xlsx/epub séparés, pdf mono+dual = une famille). smoke5 nettoie ses sorties au départ.
- smoke10/11/15 TIMEOUT dans smoke-all: veille système (journal: suspend exit 08:53, saut d'horloge 40301 s), pas un bug; chacun repasse seul en 1-7 s.

## Phase 18 — Idées post-audit (smoke18.sh; UI vérifiée dans un vrai navigateur)
done: panneau Dépendances + Disque (Système), glossaires nommés côté serveur (+ export), contexte inter-blocs dans Traduire, chaînage YouTube/Sous-titres -> Sous-titres, filtre du tray, annonce vocale (aria-live), progressbar aria.
decisions:
- maint.py: GET /api/deps (24 lignes: binaire/chemin, modèles Ollama, voix fr, langues tesseract, hint de commande + "utile pour"), GET /api/disk, POST /api/disk/clean/{uploads|logs|listen} (jamais les sorties ~/Atelier; uploads/journaux des jobs actifs épargnés).
- Glossaires: table `glossaries(name, text, updated)`, GET/PUT/DELETE /api/glossaries[/{name}] + /export; nom ≤60 car. `[\w .()'-]`. glossaryBar() ajoute une barre (choix, nom, Enregistrer/Supprimer/Exporter) au-dessus du glossaire de Traduire, Sous-titres, Documents. Remplace le partage par localStorage (perdu en repli navigateur).
- Traduire: bloc N reçoit (source, traduction) du bloc N-1 en messages (pas cumulatif), `[translate] context = true`.
- Chaînage: GET /api/jobs/{id}/file = fichier principal (srt via message; youtube = média le plus récent depuis `started`; borné au dossier de sortie). Boutons "Sous-titrer" (youtube) et "Résumer / retraduire" (subtitles) -> hash `soustitres?path=&name=` prérempli.
- Tray: filtre Toutes/En cours/Échecs; zone sr-only annonce fin/échec.
- Historique des traductions inchangé (20, spec phase 2); a11y plus poussée non faite.
env: service redémarré. Réel: 24 dépendances, 3 manquantes (ocrmypdf, gemma3:12b second/vision).
next: backlog vide côté audit. Éventuel: ocrmypdf + `ollama pull gemma3:12b` (résumé, image), contexte inter-lots pour PDF.

## Phase 19 — Version anglaise + installateur multi-distro (smoke19.sh)
done: README.md (EN) + README.fr.md, UI FR/EN (static/i18n.js + i18n.en.js, bouton langue dans la barre latérale), notes de langues EN (/api/langs: name_en, note_en), install.sh (arch/debian/fedora/suse).
decisions:
- i18n: le français reste la source et le défaut (détection navigator.language si rien de choisi). En "en": dictionnaire exact + regex appliqués aux nœuds texte et attributs title/placeholder/aria-label au chargement et par MutationObserver (écarts avec l'avis d'Opus: pas de data-t ni de t() dans chaque littéral — ~250 points à toucher; le garde-fou smoke19 vérifie que 100 % des chaînes statiques du HTML ont une traduction). Messages backend, titres de jobs (stockés en FR) et erreurs traduits à l'affichage par regex; non traduits = restent en FR sans rien casser.
- Garde-fous: smoke19 exécute translate() via node sur le vrai code; tout nouveau texte HTML sans entrée EN fait échouer le smoke.
- install.sh: familles via /etc/os-release (ID, ID_LIKE; ATELIER_OS_RELEASE pour tester). Niveaux minimal/standard/full, --dry-run, --yes, --ollama, --models, --no-{whisper,desktop,service}. Paquets installés en bloc puis un par un si échec. uv: paquet sur Arch, installateur officiel (avec confirmation) ailleurs. Real-ESRGAN/deep-filter: binaires GitHub x86_64 seulement. Ollama: paquet sur Arch, script officiel (confirmation) ailleurs.
- Non testé en réel: apt/dnf/zypper (noms de paquets de mémoire; dry-run vérifié, un paquet absent n'arrête pas le reste).
env: smoke-all quick: 364 ok, 0 FAIL.
next: choix du modèle de traduction selon la machine + repli sans LLM pour petites machines (demande en cours).

## Phase 20 — Matériel et moteur de traduction (smoke20.sh, sans aucun modèle)
done: hw.py (profil GPU AMD/NVIDIA/iGPU, RAM, cœurs, AVX2), tiers.py (palier -> modèles par rôle), engines.py (Ollama | CTranslate2+NLLB-200, pick/describe), `[translate] engine`, `[ctranslate2]`, modèles "auto", GET /api/profile + carte Système, install.sh --models (recommandés) / --engine=ct2, python -m atelier.hw.
decisions (analyse Opus):
- Paliers (VRAM totale): ≥23 Go gpu-24 (27B), ≥14 gpu-16 (12B, config actuelle), ≥7 gpu-8 et ≥3,5 gpu-4 (4B), sinon CPU: ≥15 Go RAM + AVX2 = cpu-16 (NLLB 1.3B, 4B pour le texte libre), sinon cpu-small (NLLB 600M, gemma3:1b, ni vision ni PDF).
- Valeurs explicites de config.toml toujours prioritaires; "auto" seulement si demandé. Cette machine reste sur translategemma:12b / gemma3:12b.
- engine=auto: ollama si joignable + modèle recommandé présent + palier GPU; sinon ctranslate2 si model.bin + .model présents; sinon ollama (l'erreur dit quoi installer). Jamais de téléchargement implicite.
- CT2: segment par segment (pas de prompt [n]), balises <b><i><aN> retirées (le repli texte brut existe déjà), marqueurs ⟦n⟧ re-posés en fin de segment, ≤800 car., glossaire non appliqué, langues via table NLLB (35/35). Verrous: moteur CPU prend HEAVY, pas gpu_lock. PDF refusé avec un message (pdf2zh exige Ollama): convertir en DOCX.
- install.sh --engine=ct2: pip ctranslate2 sentencepiece huggingface_hub + dépôt JustFrederik/<nllb>-ct2-int8 (id NON vérifié), confirmation avant téléchargement, stocké dans [ctranslate2] model_dir.
non testé en réel: qualité/vitesse NLLB, dépôt HF, tags gemma3:1b / translategemma:4b/27b (fakes ctranslate2 + faux sysfs dans smoke20). Argos non implémenté (NLLB le couvre).
env: smoke-all quick 407 ok. Redémarrer le service.

## Correctif — crash du moteur de rendu de la fenêtre native (2026-10-12)
- Cause: `WebKitWebProcess` (WebKitGTK 2.54) SIGABRT deux fois (09:46, 09:59), vu par coredumpctl; le service Atelier n'a pas crashé. Pas reproduit à la demande (trace sans symboles).
- Correctifs: `WEBKIT_DISABLE_DMABUF_RENDERER=1` par défaut (ATELIER_WEBKIT_SAFE=0 pour l'enlever); signal `web-process-terminated` -> rechargement de la page; >3 crashs en 2 min -> code retour 2 -> le lanceur ouvre chromium. Crash simulé (SIGABRT sur le processus de rendu): la fenêtre reste vivante et se recharge.
- Bug trouvé ensuite ("page blanche"): le crochet visait `window.native.webview`, or `window.native` n'est que la Gtk.ApplicationWindow -> jamais armé, la fenêtre restait blanche après un crash. Corrigé via `webview.platforms.gtk.BrowserView.instances[uid].webview` (+ `window.native.present()` pour le focus); rechargement par `load_uri` après 400 ms; journal `$XDG_RUNTIME_DIR/desktop.log`. Vérifié: SIGABRT du processus de rendu -> "reloaded", nouveau processus.
- Si ça persiste: `coredumpctl info <pid>` + lancer avec `ATELIER_WEBKIT_SAFE=1 WEBKIT_DISABLE_COMPOSITING_MODE=1`.

## Correctif — "Écouter" faisait crasher la fenêtre (2026-10-12)
- Cause: chaque `audio.play()` (<audio> + GStreamer) dans WebKitGTK abortait le processus de rendu; les 4 coredumps coïncident à la seconde avec la fin des jobs tts #289/#291/#293.
- Correctif: Écouter lit le wav sur la machine (atelier/player.py: pw-play > paplay > aplay > ffplay > mpv); POST /api/jobs/{id}/play, /api/play/stop, GET /api/play; le bouton bascule Écouter/Arrêter par sondage. Repli <audio> uniquement si aucun lecteur système. Fichiers limités au dossier de sortie, Origin/Sec-Fetch comme le reste de l'API.

## Dépôt public (2026-10-12)
- https://github.com/kerstz/atelier-hub (MIT, EN/FR, CI verte): README avec galerie (docs/screenshots/*.png, instance de démo vierge sur le port 7790, thème sombre EN), docs/ARCHITECTURE.md, CONTRIBUTING, SECURITY, modèles d'issues/PR, workflow CI (syntaxe + smoke 16-20), topics.
- Auteur de tous les commits réécrit en kerstz (noreply GitHub) pour apparaître dans les contributeurs; tag local `pre-authorship-rewrite` = ancien historique. Ancien dépôt privé `kerstz/atelier` (remote old-private) bloqué par GitHub: à supprimer depuis le web.
- Captures: pour les refaire, lancer une instance avec ATELIER_CONFIG pointant un config.toml à données vierges (port 7790, paths dans /tmp), créer quelques tâches via l'API, capturer 1440x900.
- Prochain: phase 21 TTS naturel (rapport Opus: Kokoro-82M par défaut + Piper en repli, catalogue de voix, aperçu, réglages, découpage par phrases).

## Phase 21 — Voix: changeur de voix + filigrane (smoke21.sh, tout hors-ligne avec faux binaires)
done: voice.py (catalogue 10 voix IA + 7 effets, job `voice` fichiers, voix perso avec case de droits, aperçu), voicelive.py (job `voice_live`, micro virtuel pw-loopback "Micro Atelier (voix)", changement de voix à chaud), voicelive_worker.py (GPL, boucle temps réel Seed-VC portée de real-time-gui.py, lu dans le vrai dépôt), voicedsp.py, UI carte Voix (onglet Audio, static/voice.js), scripts/voice-setup.sh + voice-refs.sh, Images: "Effacer un filigrane (zone)" (ffmpeg delogo).
decisions (analyse Opus):
- Moteur unique Seed-VC zéro-shot (pas de RVC: un modèle entraîné par voix, risque célébrités). Fichiers: inference.py par subprocess (cwd seedvc_dir, HF offline). Direct: modèle tiny 22 kHz, bloc 0,18 s, 6 étapes, cfg 0, porte RMS à la place du VAD funasr.
- Voix = échantillons Piper générés localement (voice-refs.sh); grave/aigu = référence décalée par rubberband. Pas de hauteur live en mode IA (pas de f0).
- Pas de repli DSP pour une voix IA (erreur explicite avec la commande); effets DSP marchent sans modèle, en direct (ffmpeg pulse) et en fichier.
- Direct = job GPU long: refusé tout de suite (409) si GPU occupé; arrêt auto à live_max_minutes.
non testé en réel: Seed-VC sur RDNA2 (ROCm torch 2.4.0 + rocm6.1), latence réelle (annoncée 300-480 ms), noms des voix Piper de voice-refs.sh (non vérifiés), pw-loopback/pacat réels. Filigrane: flou sur grande zone; pas d'inpainting IA (LaMa/IOPaint non installé), images seulement.
env: smoke21 ok. Redémarrer le service.
next: user lance scripts/voice-setup.sh puis scripts/voice-refs.sh --piper, teste le direct, mesure infer_ms.

## Phase 22 — Lecteur intégré audio/vidéo (smoke22.sh, vrai ffmpeg)
done: media.py (probe ffprobe, décision lisible-tel-quel / à préparer, job `preview` -> mp4 H.264+AAC / m4a faststart en cache, VTT depuis .srt voisin ou pistes mkv, purge cache), routes /api/jobs/{id}/media|stream|prepare|subs/{n}.vtt, /api/player/mpv; static/player.js (modal: barre maison, sous-titres, vitesse, volume, plein écran, clavier), bouton "Lire" sur les cartes de tâches; maint: cache du lecteur nettoyable; [player] dans config.toml; fenêtre native: GST_PLUGIN_FEATURE_RANK va*:NONE.
decisions (analyse Opus):
- Cause du crash <audio>: gst-plugins-good absent (autoaudiosink/qtdemux/matroskademux manquants), confiance ~85 %. Correctif réel = `sudo pacman -S --needed gst-plugins-good` (non fait par l'agent).
- Client détecté par UA: chromium (+webm/mkv natifs) vs webkitgtk (mp4/m4a/mp3/wav/ogg/opus/flac sûrs, reste préparé). Copie de flux si H.264+AAC/MP3, sinon x264 veryfast crf20.
- Garde anti-crash: sessionStorage; si la page recharge <60 s après un play(), repli mpv (fenêtre séparée) pour la session. mpv sans IPC (fenêtre à OSC); pas de pw-play pour la vidéo.
non testé en réel: lecture dans WebKitGTK 2.54 (le smoke teste le serveur, pas la vue), <track> en plein écran, sessionStorage conservé après le rechargement de la vue.
env: smoke22 ok. Installer gst-plugins-good, redémarrer le service et la fenêtre.

- Voix vérifiées par Opus (2026-10-12): homme-jeune -> mls 82 +1 dt (gilles était une voix basse), voix-aigue +3 dt, anonyme -> mls 42; licences: docs/VOICES.md (lessac/ryan NC, alan douteux).

## Phase 23 — Windows (.exe) (smoke23.sh)
done: atelier/plat.py (spawn/kill arbre, open folder, remap chemins, VRAM/RAM/AVX Windows), winlaunch.py + scripts/atelier_win.py (serveur en thread + pywebview WebView2, repli navigateur+boîte Quitter, ATELIER_NO_WINDOW=1), packaging/atelier.spec (onedir) + atelier.iss (Inno Setup), scripts/build-win.ps1 + win-setup.ps1 (winget), job CI windows-latest (build + l'exe répond + artefact), maint: conseils winget.
decisions (Opus non lancé: CLAUDE.md interdit les sous-agents, choix pris ici):
- Pas de .exe monolithique: onedir + installeur (démarrage rapide, moins de faux positifs antivirus). Outils lourds (ffmpeg, yt-dlp, Ollama, whisper) restent externes, installés par winget/à la main.
- Windows: config %APPDATA%\Atelier\config.toml (sinon config.toml embarqué), données %LOCALAPPDATA%\Atelier; remap automatique des chemins ~/.local/*.
- Hors périmètre sous Windows: voix en direct (pw-loopback), notifications, unités systemd. Conversion de fichiers/voix IA, YouTube, sous-titres, docs: mêmes CLI.
non testé en réel: TOUT le côté Windows (aucune machine): PowerShell GPU/VRAM (compteur "used" approximatif), WebView2, taskkill, build PyInstaller (hiddenimports), installeur, icône = carré bleu provisoire.
env: smoke23 ok (Linux). Prochain: lancer le job CI windows, corriger ce qui casse, tester sur un vrai Windows.

## Phase 24 — Releases .exe + .deb (smoke24.sh)
done: job `deb` dans release.yml (ubuntu-22.04, PyInstaller onedir Linux, binaire répond, scripts/build-deb.sh -> atelier_<tag>_amd64.deb, test dpkg -i), publication sur tag v* avec le .exe/zip Windows; paquet: /opt/atelier, /usr/bin/atelier (lance service systemd --user ou processus détaché, ouvre navigateur), unité user, .desktop, icône. winlaunch: Linux = serveur + navigateur (pas de pywebview), LD_LIBRARY_PATH restauré pour ffmpeg/yt-dlp. config: binaire gelé lit ~/.config/Atelier/config.toml. spec multi-plateforme.
decisions (Opus non lancé: CLAUDE.md interdit sous-agents): binaire PyInstaller dans le .deb (python 3.12 absent de Debian 12/13), outils lourds en Recommends (ffmpeg, yt-dlp). Pas de pywebview dans le .deb: simplicité.
non testé en réel: build PyInstaller Linux, dpkg -i, systemd unit (Arch sans dpkg-deb). smoke23: test quoting corrigé.
env: smoke24 ok. Release: `git tag v0.1.0 && git push --tags`.
next: pousser un tag, regarder le job CI, corriger.
- Release v0.1.0 publiée (CI verte): .exe, zip, .deb. Bug corrigé: pathex relatif + collect_submodules vide dans atelier.spec.
