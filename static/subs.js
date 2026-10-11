(() => {
  const $in = $("#st-src-in"), $src = $("#st-src"), $tgt = $("#st-tgt"), $go = $("#st-go");
  const $status = $("#st-status"), $mux = $("#st-mux"), $gloss = $("#st-gloss"), $sec = $("#tab-soustitres");
  let current = null;
  const bool = (id) => $(id).checked;

  async function takeFile(file) {
    $status.textContent = `Envoi de ${file.name}…`;
    try {
      $in.value = await uploadFile(file);
      $status.textContent = `${file.name} prêt.`;
    } catch {
      $status.textContent = "Envoi échoué.";
    }
  }

  async function go() {
    const source = $in.value.trim();
    if (!source || current) return;
    store.set("st.src", $src.value);
    store.set("st.tgt", $tgt.value);
    store.set("st.mux", $mux.checked ? "1" : "");
    store.set("st.tr", bool("#st-tr") ? "1" : "");
    store.set("tr.gloss", $gloss.value);
    $go.disabled = true;
    $status.textContent = "En file…";
    const r = await post("/api/jobs", {
      kind: "subtitles",
      title: `Sous-titres : ${source.split("/").pop().slice(0, 40)}`,
      params: {
        source, src: $src.value, tgt: $tgt.value, translate: bool("#st-tr"), mux: $mux.checked,
        force_whisper: bool("#st-force"), quality: $("#st-q").value, glossary: $gloss.value,
      },
    });
    if (!r.ok) {
      $status.textContent = "Erreur de lancement.";
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

  $("#st-pick").onclick = () => $("#st-file").click();
  $("#st-file").onchange = (e) => e.target.files[0] && takeFile(e.target.files[0]);
  $mux.onchange = () => ($("#st-q-wrap").hidden = !$mux.checked);
  ["dragover", "dragenter"].forEach((ev) =>
    $sec.addEventListener(ev, (e) => {
      e.preventDefault();
      $sec.classList.add("drop");
    })
  );
  ["dragleave", "drop"].forEach((ev) => $sec.addEventListener(ev, () => $sec.classList.remove("drop")));
  $sec.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) takeFile(e.dataTransfer.files[0]);
  });
  $go.onclick = go;

  (async () => {
    const langs = await (await fetch("/api/langs")).json();
    langs.forEach((l) => {
      $src.append(new Option(l.name, l.code));
      if (l.code !== "auto") $tgt.append(new Option(l.name, l.code));
    });
    $src.value = store.get("st.src", "en");
    $tgt.value = store.get("st.tgt", "fr");
    $mux.checked = !!store.get("st.mux", "");
    $("#st-tr").checked = store.get("st.tr", "1") === "1";
    $("#st-q-wrap").hidden = !$mux.checked;
    $gloss.value = store.get("tr.gloss", "");
  })();
})();
