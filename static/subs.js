(() => {
  const $in = $("#st-src-in"), $src = $("#st-src"), $tgt = $("#st-tgt"), $go = $("#st-go");
  const $status = $("#st-status"), $mux = $("#st-mux"), $gloss = $("#st-gloss"), $chip = $("#st-chip");
  let current = null, picked = null;
  const bool = (id) => $(id).checked;

  function showChip() {
    ui.chips($chip, picked ? [picked] : [], () => {
      picked = null;
      $in.value = "";
      showChip();
    });
  }

  async function takeFile(file) {
    $status.textContent = `Envoi de ${file.name}…`;
    try {
      $in.value = await uploadFile(file);
      picked = {name: file.name};
      showChip();
      $status.textContent = "";
    } catch {
      $status.textContent = "Envoi échoué.";
      ui.toast(`Envoi échoué : ${file.name}`, "bad");
    }
  }

  async function go() {
    const source = $in.value.trim();
    if (!source) return ($status.textContent = "Choisir un fichier ou saisir une URL.");
    if (current) return;
    store.set("st.src", $src.value);
    store.set("st.tgt", $tgt.value);
    store.set("st.mux", $mux.checked ? "1" : "");
    store.set("st.tr", bool("#st-tr") ? "1" : "");
    store.set("tr.gloss", $gloss.value);
    $go.disabled = true;
    $status.textContent = "En file…";
    const r = await post("/api/jobs", {
      kind: "subtitles",
      title: `Sous-titres : ${(picked?.name || source.split("/").pop()).slice(0, 40)}`,
      params: {
        source, src: $src.value, tgt: $tgt.value, translate: bool("#st-tr"), mux: $mux.checked,
        force_whisper: bool("#st-force"), quality: $("#st-q").value, glossary: $gloss.value,
      },
    });
    if (!r.ok) {
      $status.textContent = "Erreur de lancement.";
      ui.toast("Erreur de lancement", "bad");
      $go.disabled = false;
      return;
    }
    current = (await r.json()).id;
  }

  bus.addEventListener("job", (e) => {
    const j = e.detail;
    if (j.id !== current) return;
    if (j.status === "running") $status.textContent = j.message || "En cours…";
    if (["done", "failed", "cancelled"].includes(j.status)) {
      $status.textContent = {done: `Terminé : ${j.message}`, failed: `Échec : ${j.error}`, cancelled: "Annulé."}[j.status];
      current = null;
      $go.disabled = false;
    }
  });

  ui.dropzone($("#st-drop"), {onFiles: (fs) => takeFile(fs[0])});
  $in.addEventListener("input", () => {
    if (picked) {
      picked = null;
      showChip();
    }
  });
  $mux.onchange = () => ($("#st-q-wrap").hidden = !$mux.checked);
  $go.onclick = go;
  jobsView($("#st-result"), (j) => j.kind === "subtitles", {icon: "captions", title: "Rien pour l'instant", hint: "Les fichiers .srt produits sont listés ici."});

  (async () => {
    const langs = await (await fetch("/api/langs")).json();
    ui.select($src, langs.map((l) => [l.code, l.name]), store.get("st.src", "en"));
    ui.select($tgt, langs.filter((l) => l.code !== "auto").map((l) => [l.code, l.name]), store.get("st.tgt", "fr"));
    $mux.checked = !!store.get("st.mux", "");
    $("#st-tr").checked = store.get("st.tr", "1") === "1";
    $("#st-q-wrap").hidden = !$mux.checked;
    $gloss.value = store.get("tr.gloss", "");
  })();
})();
