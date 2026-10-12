(() => {
  const $list = $("#dc-list"), $go = $("#dc-go"), $status = $("#dc-status");
  const $src = $("#dc-src"), $tgt = $("#dc-tgt"), $gloss = $("#dc-gloss"), $pages = $("#dc-pages");
  const files = [];

  function render() {
    ui.chips($list, files, (i) => {
      files.splice(i, 1);
      render();
    });
    $go.disabled = files.length === 0;
    $("#dc-ocr-go").disabled = !files.some((f) => /\.pdf$/i.test(f.name));
  }

  async function add(fileList) {
    for (const file of fileList) {
      $status.textContent = `Envoi de ${file.name}…`;
      try {
        files.push({name: file.name, path: await uploadFile(file)});
      } catch {
        $status.textContent = `Envoi échoué : ${file.name}`;
        ui.toast(`Envoi échoué : ${file.name}`, "bad");
        break;
      }
      render();
    }
    if (/^(Envoi de|Uploading)/.test($status.textContent)) $status.textContent = "";
  }

  async function go() {
    if (!files.length) return;
    store.set("dc.src", $src.value);
    store.set("dc.tgt", $tgt.value);
    store.set("tr.gloss", $gloss.value);
    $go.disabled = true;
    let ok = 0;
    for (const f of files) {
      const r = await post("/api/jobs", {
        kind: "document",
        title: `Document : ${f.name.slice(0, 40)}`,
        params: {path: f.path, src: $src.value, tgt: $tgt.value, glossary: $gloss.value, pages: $pages.value, ocr: $("#dc-ocr").checked},
      });
      if (r.ok) ok++;
    }
    files.length = 0;
    render();
    $status.textContent = `${ok} tâche(s) lancée(s).`;
  }

  ui.dropzone($("#dc-drop"), {multiple: true, onFiles: add});
  $("#dc-clear").onclick = () => {
    files.length = 0;
    render();
  };
  $go.onclick = go;
  $("#dc-ocr-go").onclick = async () => {
    const pdfs = files.filter((f) => /\.pdf$/i.test(f.name));
    if (!pdfs.length) return ($status.textContent = "OCR : ajouter au moins un PDF.");
    let ok = 0;
    for (const f of pdfs) {
      const r = await post("/api/jobs", {
        kind: "ocr", title: `OCR : ${f.name.slice(0, 40)}`, params: {path: f.path, force: $("#dc-force").checked},
      });
      if (r.ok) ok++;
      files.splice(files.indexOf(f), 1);
    }
    render();
    $status.textContent = `${ok} OCR lancé(s).`;
  };
  jobsView($("#dc-result"), (j) => j.kind === "document" || j.kind === "ocr", {icon: "file-text", title: "Rien pour l'instant", hint: "Les documents traduits et PDF océrisés sont enregistrés dans le dossier Atelier › docs.", limit: 8});

  glossaryBar($gloss);
  (async () => {
    const langs = await (await fetch("/api/langs")).json();
    ui.langPicker($src, langs, {value: store.get("dc.src", "en"), prefix: "Source"});
    ui.langPicker($tgt, langs, {value: store.get("dc.tgt", "fr"), auto: false, prefix: "Cible"});
    $gloss.value = store.get("tr.gloss", "");
  })();
})();
