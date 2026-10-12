(() => {
  const root = $("#vc-root");
  if (!root) return;
  const h = ui.h;
  let voices = [], lang = store.get("vc.lang", "fr"), sel = store.get("vc.voice", ""), live = {running: false}, files = [], timer = null;
  const get = async (u) => (await fetch(u)).json();
  const err = async (r) => ui.toast((await r.json().catch(() => ({}))).detail || "Échec", "bad");

  const head = h("div", "card-head");
  head.append(h("h2", null, "Voix"));
  const note = h("p", "dim", "Change la voix d'un fichier ou de ton micro en direct. Moteur IA (Seed-VC, GPU) pour les voix réalistes, effets simples sans modèle.");
  const grid = h("div", "voice-grid");
  const fileBox = h("div", "field-row wrap");
  const liveBox = h("div", "field-row wrap");
  const status = h("div", "dim");
  const addBox = h("details");
  root.append(head, note, grid, fileBox, liveBox, status, addBox);

  const langBar = h("div", "field-row");
  function drawLang() {
    langBar.replaceChildren(h("span", "dim", "Langue des voix"));
    for (const [code, label] of [["fr", "Français"], ["en", "English"]]) {
      const b = h("button", "btn" + (lang === code ? " primary" : ""), label);
      b.type = "button";
      b.onclick = () => {
        lang = code;
        store.set("vc.lang", lang);
        const cur = voices.find((v) => v.id === sel);
        if (cur && cur.kind === "ai" && cur.lang !== lang) sel = (voices.find((v) => v.lang === lang && v.ready) ?? voices.find((v) => v.kind === "fx"))?.id ?? "";
        store.set("vc.voice", sel);
        drawLang();
        drawGrid();
      };
      langBar.append(b);
    }
  }
  root.insertBefore(langBar, grid);

  function drawGrid() {
    grid.replaceChildren();
    for (const v of voices.filter((x) => x.kind === "fx" || x.lang === lang)) {
      const b = h("button", "btn voice" + (v.id === sel ? " primary" : ""));
      b.type = "button";
      b.disabled = false;
      b.title = v.ready ? v.desc : `${v.desc} — non installée (scripts/voice-setup.sh + scripts/voice-refs.sh)`;
      b.append(h("strong", null, v.name), h("span", "dim", v.kind === "fx" ? "effet" : v.ready ? "réaliste" : "non installée"));
      if (!v.ready) b.classList.add("off");
      b.onclick = async () => {
        sel = v.id;
        store.set("vc.voice", sel);
        drawGrid();
        if (live.running && v.ready) {
          const r = await post("/api/voice/live/set", {voice: v.id});
          if (!r.ok) err(r);
        }
      };
      b.ondblclick = async () => {
        const r = await post("/api/voice/preview", {voice: v.id});
        if (!r.ok) err(r);
      };
      grid.append(b);
    }
    $("#vc-go") && ($("#vc-go").disabled = !files.length || !sel);
  }

  function drawFile() {
    fileBox.replaceChildren();
    const drop = h("div", "dropzone-lite");
    drop.append(h("strong", null, "Convertir un fichier"), h("span", "dim", "déposer audio ou vidéo"));
    const fmt = h("select");
    ui.select(fmt, [["wav", "WAV"], ["mp3", "MP3"], ["flac", "FLAC"], ["mkv", "Vidéo (mkv)"]], store.get("vc.fmt", "mp3"));
    fmt.onchange = () => store.set("vc.fmt", fmt.value);
    const lab = (t, el) => { const l = h("label", "inline", t + " "); l.append(el); return l; };
    const sep = h("input"); sep.type = "checkbox"; sep.checked = store.get("vc.sep", "1") === "1";
    sep.onchange = () => store.set("vc.sep", sep.checked ? "1" : "0");
    const keep = h("input"); keep.type = "checkbox"; keep.checked = store.get("vc.keep", "1") === "1";
    keep.onchange = () => store.set("vc.keep", keep.checked ? "1" : "0");
    const go = h("button", "btn primary", "Convertir");
    go.id = "vc-go"; go.type = "button"; go.disabled = !files.length || !sel;
    const chips = h("div", "chips");
    ui.chips(chips, files, (i) => { files.splice(i, 1); drawFile(); });
    go.onclick = async () => {
      const v = voices.find((x) => x.id === sel);
      if (!v) return;
      go.disabled = true;
      let ok = 0;
      for (const f of files) {
        const r = await post("/api/jobs", {kind: "voice", title: `Voix « ${v.name} » : ${f.name.slice(0, 30)}`,
          params: {path: f.path, voice: v.id, format: fmt.value, separate: sep.checked, keep_music: keep.checked}});
        if (r.ok) ok++;
      }
      files.length = 0;
      drawFile();
      status.textContent = `${ok} tâche(s) lancée(s).`;
    };
    fileBox.append(drop, chips, lab("Format", fmt), lab("Séparer la voix", sep), lab("Garder la musique", keep), go);
    ui.dropzone(drop, {multiple: true, onFiles: async (fl) => {
      for (const f of fl) {
        status.textContent = `Envoi de ${f.name}…`;
        try { files.push({name: f.name, path: await uploadFile(f)}); } catch { ui.toast(`Envoi échoué : ${f.name}`, "bad"); break; }
      }
      status.textContent = "";
      drawFile();
    }});
  }

  async function drawLive() {
    liveBox.replaceChildren();
    const src = h("select");
    let inputs = [];
    try { inputs = (await get("/api/voice/inputs")).inputs; } catch {}
    ui.select(src, [["", "Micro par défaut"], ...inputs.map((i) => [i.name, i.desc])], store.get("vc.src", ""));
    src.onchange = () => store.set("vc.src", src.value);
    src.disabled = live.running;
    const start = h("button", "btn primary", live.running ? "Arrêter le direct" : "Démarrer le direct");
    start.type = "button";
    start.onclick = async () => {
      start.disabled = true;
      const r = live.running ? await post("/api/voice/live/stop") : await post("/api/voice/live/start", {voice: sel, source: src.value});
      if (!r.ok) err(r);
      setTimeout(poll, 600);
    };
    const mk = (label, key) => {
      const b = h("button", "btn" + (live[key] ? " primary" : ""), label);
      b.type = "button"; b.disabled = !live.running || live.engine !== "seedvc";
      b.onclick = async () => { await post("/api/voice/live/set", {[key]: !live[key]}); setTimeout(poll, 300); };
      return b;
    };
    const l = h("label", "inline", "Source "); l.append(src);
    const info = h("span", "dim");
    if (live.running) {
      const s = live.stats || {};
      info.textContent = live.ready
        ? `En direct → « Micro Atelier (voix) »` + (s.infer_ms != null ? ` · ${s.infer_ms} ms/bloc · entrée ${s.in_db} dB` : "") + (s.overruns ? ` · ${s.overruns} retard(s)` : "")
        : "Chargement du modèle…";
    } else info.textContent = "Dans Discord/OBS, choisir « Micro Atelier (voix) » comme micro.";
    liveBox.append(l, start, mk("Contourner", "bypass"), mk("Muet", "mute"), info);
  }

  async function poll() {
    try { live = await get("/api/voice/live"); } catch { live = {running: false}; }
    await drawLive();
    clearTimeout(timer);
    timer = setTimeout(poll, live.running ? 1000 : 5000);
  }

  function drawAdd() {
    addBox.replaceChildren(h("summary", null, "Ajouter ma propre voix"));
    const name = h("input"); name.placeholder = "Nom de la voix"; name.maxLength = 40;
    const rights = h("input"); rights.type = "checkbox";
    const l = h("label", "inline", "J'ai le droit d'utiliser cette voix "); l.append(rights);
    const drop = h("div", "dropzone-lite");
    drop.append(h("strong", null, "Échantillon"), h("span", "dim", "10 à 30 s de parole propre, une seule personne"));
    addBox.append(name, l, drop);
    ui.dropzone(drop, {onFiles: async ([f]) => {
      if (!name.value.trim() || !rights.checked) return ui.toast("Nom et confirmation requis", "bad");
      try {
        const path = await uploadFile(f);
        const r = await post("/api/voice/voices", {path, name: name.value, rights: rights.checked, lang});
        if (!r.ok) return err(r);
        name.value = ""; rights.checked = false;
        await load();
      } catch { ui.toast("Envoi échoué", "bad"); }
    }});
  }

  async function load() {
    const d = await get("/api/voice/voices");
    voices = d.voices;
    const cur = voices.find((v) => v.id === sel);
    if (cur && cur.kind === "ai") lang = cur.lang || lang;
    if (!cur) sel = (voices.find((v) => v.ready && v.lang === lang) ?? voices.find((v) => v.ready) ?? voices[0])?.id ?? "";
    drawLang();
    drawGrid();
    drawFile();
  }

  const res = h("div");
  root.after(res);
  jobsView(res, (j) => j.kind === "voice" || j.kind === "voice_live", {icon: "mic", title: "Rien pour l'instant", hint: "Les fichiers sont enregistrés dans ~/Atelier/audio.", limit: 10});
  drawAdd();
  load().then(poll);
})();
