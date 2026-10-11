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
