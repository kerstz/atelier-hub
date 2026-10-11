(() => {
  const $list = $("#cv-list"), $groups = $("#cv-groups"), $go = $("#cv-go"), $zip = $("#cv-zip"), $status = $("#cv-status");
  const CAT = {video: "Vidéo", audio: "Audio", image: "Images", text: "Documents", sheet: "Tableurs", slide: "Présentations", ebook: "E-books"};
  const QUALITY = [["high", "Qualité haute"], ["normal", "Qualité normale"], ["low", "Fichier léger"]];
  const SIZES = {
    video: [["0", "Taille d'origine"], ["1080", "1080p max"], ["720", "720p max"], ["480", "480p max"]],
    image: [["0", "Taille d'origine"], ["3840", "3840 px max"], ["2560", "2560 px max"], ["1920", "1920 px max"], ["1280", "1280 px max"], ["800", "800 px max"]],
  };
  const LOSSY = {video: true, audio: true, image: true};
  const files = [];
  const pick = {};
  let lastIds = [];

  function targetsOf(cat) {
    const sets = files.filter((f) => f.category === cat).map((f) => f.targets);
    const first = sets[0] ?? [];
    return first.filter((t) => sets.every((s) => s.some((x) => x.id === t.id)));
  }

  function renderGroups() {
    const cats = [...new Set(files.map((f) => f.category))];
    $groups.replaceChildren(
      ...cats.map((cat) => {
        const n = files.filter((f) => f.category === cat).length;
        const row = ui.h("div", "cv-group");
        row.append(ui.h("strong", null, `${CAT[cat]} · ${n} fichier${n > 1 ? "s" : ""}`));
        const ts = targetsOf(cat);
        const sel = ui.h("select");
        ui.select(sel, ts.map((t) => [t.id, t.label]), pick[cat]?.target ?? store.get(`cv.${cat}`, ts[0]?.id));
        if (!sel.value && ts.length) sel.selectedIndex = 0;
        pick[cat] = {...pick[cat], target: sel.value};
        sel.onchange = () => {
          pick[cat].target = sel.value;
          store.set(`cv.${cat}`, sel.value);
          renderGroups();
        };
        row.append(sel);
        if (!ts.length) row.append(ui.h("span", "dim", "aucun format commun"));
        const isLossy = LOSSY[cat] && !/flac|wav|png/.test(sel.value);
        if (isLossy) {
          const q = ui.h("select");
          ui.select(q, QUALITY, pick[cat].quality ?? "normal");
          q.onchange = () => (pick[cat].quality = q.value);
          pick[cat].quality ??= "normal";
          row.append(q);
        }
        if (SIZES[cat]) {
          const z = ui.h("select");
          ui.select(z, SIZES[cat], pick[cat].size ?? "0");
          z.onchange = () => (pick[cat].size = z.value);
          pick[cat].size ??= "0";
          row.append(z);
        }
        return row;
      })
    );
  }

  function render() {
    ui.chips($list, files, (i) => {
      files.splice(i, 1);
      render();
    });
    renderGroups();
    $go.disabled = files.length === 0 || files.some((f) => !targetsOf(f.category).length);
  }

  async function add(fileList) {
    for (const file of fileList) {
      $status.textContent = `Envoi de ${file.name}…`;
      try {
        const path = await uploadFile(file);
        const r = await post("/api/convert/detect", {path});
        const d = await r.json();
        if (!d.category) {
          ui.toast(`Format non reconnu : ${file.name}`, "bad");
          continue;
        }
        files.push({name: file.name, path, category: d.category, targets: d.targets});
      } catch {
        ui.toast(`Envoi échoué : ${file.name}`, "bad");
        break;
      }
      render();
    }
    $status.textContent = "";
  }

  async function go() {
    if ($go.disabled) return;
    $go.disabled = true;
    lastIds = [];
    for (const f of files) {
      const p = pick[f.category];
      const label = targetsOf(f.category).find((t) => t.id === p.target)?.label ?? p.target;
      const r = await post("/api/jobs", {
        kind: "convert",
        title: `Convertir : ${f.name.slice(0, 36)} → ${label}`,
        params: {path: f.path, target: p.target, quality: p.quality ?? "normal", size: Number(p.size ?? 0)},
      });
      if (r.ok) lastIds.push((await r.json()).id);
    }
    $status.textContent = `${lastIds.length} tâche(s) lancée(s).`;
    files.length = 0;
    render();
    refreshZip();
  }

  function refreshZip() {
    $zip.disabled = !lastIds.some((id) => jobs.get(id)?.status === "done");
  }

  ui.dropzone($("#cv-drop"), {multiple: true, onFiles: add});
  $("#cv-clear").onclick = () => {
    files.length = 0;
    render();
  };
  $go.onclick = go;
  $zip.onclick = () => {
    const ids = lastIds.filter((id) => jobs.get(id)?.status === "done");
    if (ids.length) location.href = `/api/convert/zip?ids=${ids.join(",")}`;
  };
  bus.addEventListener("job", refreshZip);
  bus.addEventListener("jobs", refreshZip);
  jobsView($("#cv-result"), (j) => j.kind === "convert", {icon: "swap", title: "Rien pour l'instant", hint: "Les fichiers convertis sont enregistrés dans ~/Atelier/convert.", limit: 12});
  render();
})();
