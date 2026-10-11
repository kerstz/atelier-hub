(() => {
  const $zone = $("#dc-drop"), $list = $("#dc-list"), $go = $("#dc-go"), $status = $("#dc-status");
  const $src = $("#dc-src"), $tgt = $("#dc-tgt"), $gloss = $("#dc-gloss"), $pages = $("#dc-pages");
  const files = [];

  function render() {
    $list.replaceChildren();
    files.forEach((f, i) => {
      const li = el("li");
      const row = el("div", null, "row");
      row.append(el("span", f.name));
      const b = el("button", "Retirer");
      b.onclick = () => {
        files.splice(i, 1);
        render();
      };
      row.append(b);
      li.append(row);
      $list.append(li);
    });
    $go.disabled = files.length === 0;
  }

  async function add(fileList) {
    for (const file of fileList) {
      $status.textContent = `Envoi de ${file.name}…`;
      try {
        files.push({name: file.name, path: await uploadFile(file)});
      } catch {
        $status.textContent = `Envoi échoué : ${file.name}`;
        return;
      }
    }
    $status.textContent = "";
    render();
  }

  async function go() {
    store.set("dc.src", $src.value);
    store.set("dc.tgt", $tgt.value);
    store.set("tr.gloss", $gloss.value);
    $go.disabled = true;
    let ok = 0;
    for (const f of files) {
      const r = await post("/api/jobs", {
        kind: "document",
        title: `Document : ${f.name.slice(0, 40)}`,
        params: {path: f.path, src: $src.value, tgt: $tgt.value, glossary: $gloss.value, pages: $pages.value},
      });
      if (r.ok) ok++;
    }
    files.length = 0;
    render();
    $status.textContent = `${ok} tâche(s) lancée(s) — voir le panneau Tâches.`;
  }

  ["dragover", "dragenter"].forEach((ev) =>
    $zone.addEventListener(ev, (e) => {
      e.preventDefault();
      $zone.classList.add("drop");
    })
  );
  ["dragleave", "drop"].forEach((ev) => $zone.addEventListener(ev, () => $zone.classList.remove("drop")));
  $zone.addEventListener("drop", (e) => {
    e.preventDefault();
    add(e.dataTransfer.files);
  });
  $("#dc-pick").onclick = () => $("#dc-file").click();
  $("#dc-file").onchange = (e) => add(e.target.files);
  $("#dc-clear").onclick = () => {
    files.length = 0;
    render();
  };
  $go.onclick = go;

  (async () => {
    const langs = await (await fetch("/api/langs")).json();
    langs.forEach((l) => {
      $src.append(new Option(l.name, l.code));
      if (l.code !== "auto") $tgt.append(new Option(l.name, l.code));
    });
    $src.value = store.get("dc.src", "en");
    $tgt.value = store.get("dc.tgt", "fr");
    $gloss.value = store.get("tr.gloss", "");
  })();
})();
