(() => {
  const $in = $("#tr-in"), $out = $("#tr-out"), $src = $("#tr-src"), $tgt = $("#tr-tgt");
  const $go = $("#tr-go"), $cancel = $("#tr-cancel"), $status = $("#tr-status"), $gloss = $("#tr-gloss");
  const bufs = new Map();
  let langs = [], current = null, image = null, dictJob = null;
  const IMG = /^image\/(png|jpeg|webp)$/;

  function showImage() {
    ui.chips($("#tr-chip"), image ? [image] : [], () => {
      image = null;
      showImage();
    });
    $in.disabled = !!image;
    $in.placeholder = image ? "Image jointe : le texte sera lu dans l'image." : "Texte à traduire…";
  }

  async function takeImage(file) {
    if (!IMG.test(file.type)) return ui.toast("Image png, jpg ou webp uniquement", "bad");
    $status.textContent = "Envoi de l'image…";
    try {
      image = {name: file.name || "capture.png", path: await uploadFile(file)};
      $status.textContent = "";
      showImage();
    } catch {
      $status.textContent = "Envoi échoué.";
      ui.toast("Envoi échoué", "bad");
    }
  }

  let paintLangs = () => {};

  function fillLangs() {
    const a = ui.langPicker($src, langs, {value: store.get("tr.src", "auto"), prefix: "Source"});
    const b = ui.langPicker($tgt, langs, {value: store.get("tr.tgt", "fr"), auto: false, prefix: "Cible"});
    paintLangs = () => (a(), b());
    $gloss.value = store.get("tr.gloss", "");
  }

  const name = (c) => {
    const l = langs.find((x) => x.code === c);
    return l ? i18n.pick(l, "name") : c;
  };

  function setBusy(busy) {
    $go.hidden = busy;
    $cancel.hidden = !busy;
  }

  async function go() {
    const text = $in.value.trim();
    if ((!text && !image) || current) return;
    store.set("tr.src", $src.value);
    store.set("tr.tgt", $tgt.value);
    store.set("tr.gloss", $gloss.value);
    $out.value = "";
    $status.textContent = "En file…";
    setBusy(true);
    const sent = image;
    const title = `Traduction ${$src.value}→${$tgt.value} : ${sent ? `image ${sent.name}` : text.slice(0, 30)}`;
    const r = await post("/api/jobs", {
      kind: "translate",
      title,
      params: {text, image: sent?.path, src: $src.value, tgt: $tgt.value, glossary: $gloss.value},
    });
    if (!r.ok) {
      $status.textContent = "Erreur de lancement.";
      ui.toast("Erreur de lancement", "bad");
      setBusy(false);
      return;
    }
    current = (await r.json()).id;
    if (sent) {
      image = null; // le serveur consomme l'upload
      showImage();
    }
    $out.value = bufs.get(current) ?? "";
    settle(current);
  }

  bus.addEventListener("delta", (e) => {
    const {id, text} = e.detail;
    if (id === dictJob) return;
    bufs.set(id, (bufs.get(id) ?? "") + text);
    if (id === current) {
      $out.value = bufs.get(id);
      $out.scrollTop = $out.scrollHeight;
    }
  });

  bus.addEventListener("job", (e) => {
    const j = e.detail;
    if (j.id !== current) return;
    if (j.status === "running") $status.textContent = j.message || "En cours…";
    if (["done", "failed", "cancelled"].includes(j.status)) {
      $status.textContent = {done: "Terminé.", failed: `Échec : ${j.error}`, cancelled: "Annulé."}[j.status];
      bufs.delete(j.id);
      current = null;
      setBusy(false);
      if (j.status === "done") loadHistory();
    }
  });

  // ---- dictée (micro -> whisper -> champ source) et lecture (Piper)
  const $mic = $("#tr-mic"), $listen = $("#tr-listen"), $mp3 = $("#tr-mp3");
  const label = (b, t) => (b.querySelector("span").textContent = t);
  let rec = null, recTimer = null, audio = null, ttsJob = null, ttsMode = null;

  async function toggleMic() {
    if (rec) return rec.stop();
    if (dictJob) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") return ui.toast("Micro indisponible", "bad");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
    } catch {
      return ui.toast("Accès au micro refusé", "bad");
    }
    const chunks = [];
    const r = (rec = new MediaRecorder(stream));
    const t0 = Date.now();
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    r.onstop = async () => {
      clearInterval(recTimer);
      stream.getTracks().forEach((t) => t.stop());
      rec = null;
      label($mic, "Dicter");
      $mic.classList.remove("danger");
      if (!chunks.length) return;
      $status.textContent = "Envoi de la dictée…";
      try {
        const file = new File(chunks, "dictee.webm", {type: chunks[0].type || "audio/webm"});
        const path = await uploadFile(file);
        const res = await post("/api/jobs", {kind: "dictate", title: "Dictée", params: {path, lang: $src.value}});
        if (!res.ok) throw new Error();
        dictJob = (await res.json()).id;
        $status.textContent = "Transcription…";
      } catch {
        $status.textContent = "";
        ui.toast("Dictée échouée", "bad");
      }
    };
    r.start();
    $mic.classList.add("danger");
    recTimer = setInterval(() => {
      const s = Math.round((Date.now() - t0) / 1000);
      label($mic, `Arrêter ${s} s`);
      if (s >= 300) r.stop();
    }, 500);
    label($mic, "Arrêter 0 s");
  }

  function stopAudio() {
    audio?.pause();
    audio = null;
    label($listen, "Écouter");
  }

  async function speak(mode) {
    if (mode === "listen" && audio) return stopAudio();
    const text = $out.value.trim();
    if (!text || ttsJob) return;
    ttsMode = mode;
    const r = await post("/api/jobs", {kind: "tts", title: `Lecture ${$tgt.value} : ${text.slice(0, 30)}`, params: {text, lang: $tgt.value, mode}});
    if (!r.ok) return ui.toast("Erreur de lancement", "bad");
    ttsJob = (await r.json()).id;
    $status.textContent = mode === "mp3" ? "Export mp3…" : "Synthèse vocale…";
  }

  bus.addEventListener("delta", (e) => {
    if (e.detail.id !== dictJob) return;
    $in.value = ($in.value ? $in.value.trimEnd() + " " : "") + e.detail.text;
    $in.focus();
  });
  bus.addEventListener("job", (e) => {
    const j = e.detail;
    if (!["done", "failed", "cancelled"].includes(j.status)) return;
    if (j.id === dictJob) {
      dictJob = null;
      $status.textContent = j.status === "done" ? "Dictée ajoutée." : `Dictée : ${j.error || "annulée"}`;
    } else if (j.id === ttsJob) {
      ttsJob = null;
      if (j.status !== "done") return ($status.textContent = `Lecture : ${j.error || "annulée"}`);
      $status.textContent = "";
      if (ttsMode === "mp3") return ui.toast("MP3 enregistré dans ~/Atelier/audio", "ok");
      audio = new Audio(`/api/jobs/${j.id}/download`);
      audio.onended = audio.onerror = stopAudio;
      label($listen, "Arrêter");
      audio.play().catch(stopAudio);
    }
  });
  $mic.onclick = toggleMic;
  $listen.onclick = () => speak("listen");
  $mp3.onclick = () => speak("mp3");

  async function loadHistory() {
    const ul = $("#tr-hist");
    if (!ul.children.length) ul.replaceChildren(ui.skeleton(2));
    const rows = await (await fetch("/api/translations")).json();
    ul.replaceChildren();
    if (!rows.length) ul.append(ui.empty("history", "Pas encore d'historique", "Les 20 dernières traductions apparaissent ici."));
    rows.forEach((h) => {
      const li = el("li");
      li.append(el("div", `${name(h.src)} → ${name(h.tgt)}`, "dim"), el("div", h.source, "clip"), el("div", h.result, "clip dim"));
      li.tabIndex = 0;
      li.onkeydown = (e) => e.key === "Enter" && li.click();
      li.onclick = () => {
        $in.value = h.source;
        $out.value = h.result;
        $src.value = h.src;
        $tgt.value = h.tgt;
        paintLangs();
      };
      ul.append(li);
    });
  }

  bus.addEventListener("prefill", (e) => {
    const text = e.detail.tab === "traduire" && e.detail.params.get("text");
    if (!text) return;
    $in.value = text;
    $in.focus();
  });

  $go.onclick = go;
  ui.dropzone($("#tr-drop"), {onFiles: (fs) => takeImage(fs[0])});
  $cancel.onclick = () => current && post(`/api/jobs/${current}/cancel`);
  $("#tr-swap").onclick = () => {
    if ($src.value === "auto") return;
    [$src.value, $tgt.value] = [$tgt.value, $src.value];
    paintLangs();
    [$in.value, $out.value] = [$out.value, $in.value];
  };
  ui.copy($("#tr-copy"), () => $out.value);
  $("#tr-hclear").onclick = async () => {
    if (!(await ui.modal({title: "Vider l'historique ?", body: "Les traductions enregistrées seront supprimées.", confirm: "Vider", danger: true}))) return;
    await post("/api/translations/clear");
    loadHistory();
  };

  glossaryBar($gloss);
  (async () => {
    langs = await (await fetch("/api/langs")).json();
    fillLangs();
    loadHistory();
  })();
})();
