(() => {
  const $in = $("#tr-in"), $out = $("#tr-out"), $src = $("#tr-src"), $tgt = $("#tr-tgt");
  const $go = $("#tr-go"), $cancel = $("#tr-cancel"), $status = $("#tr-status"), $gloss = $("#tr-gloss");
  const bufs = new Map();
  let langs = [], current = null, image = null;
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

  function fillLangs() {
    langs.forEach((l) => {
      $src.append(new Option(l.name, l.code));
      if (l.code !== "auto") $tgt.append(new Option(l.name, l.code));
    });
    $src.value = store.get("tr.src", "auto");
    $tgt.value = store.get("tr.tgt", "fr");
    $gloss.value = store.get("tr.gloss", "");
  }

  const name = (c) => langs.find((l) => l.code === c)?.name ?? c;

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
  }

  bus.addEventListener("delta", (e) => {
    const {id, text} = e.detail;
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
      };
      ul.append(li);
    });
  }

  $go.onclick = go;
  ui.dropzone($("#tr-drop"), {onFiles: (fs) => takeImage(fs[0])});
  $cancel.onclick = () => current && post(`/api/jobs/${current}/cancel`);
  $("#tr-swap").onclick = () => {
    if ($src.value === "auto") return;
    [$src.value, $tgt.value] = [$tgt.value, $src.value];
    [$in.value, $out.value] = [$out.value, $in.value];
  };
  ui.copy($("#tr-copy"), () => $out.value);
  $("#tr-hclear").onclick = async () => {
    if (!(await ui.modal({title: "Vider l'historique ?", body: "Les traductions enregistrées seront supprimées.", confirm: "Vider", danger: true}))) return;
    await post("/api/translations/clear");
    loadHistory();
  };

  (async () => {
    langs = await (await fetch("/api/langs")).json();
    fillLangs();
    loadHistory();
  })();
})();
