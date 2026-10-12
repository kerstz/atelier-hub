(() => {
  // Onglets Images et Audio : même schéma (dropzone -> une tâche par fichier).
  function tab({p, kind, accept, actions, formats, title}) {
    const $list = $(`#${p}-list`), $go = $(`#${p}-go`), $status = $(`#${p}-status`), $act = $(`#${p}-action`);
    const files = [];
    ui.select($act, actions.map((a) => [a.id, a.label]), store.get(`${p}.action`, actions[0].id));
    if (!$act.value) $act.selectedIndex = 0;
    const cur = () => actions.find((a) => a.id === $act.value) ?? actions[0];

    const $opt = $(`#${p}-fmt`) ?? $(`#${p}-style`);
    function opts() {
      const list = cur().options ?? [];
      $opt.closest("label").hidden = !list.length;
      ui.select($opt, list, store.get(`${p}.${cur().id}`, list[0]?.[0]));
      if (!$opt.value && list.length) $opt.selectedIndex = 0;
    }

    function render() {
      ui.chips($list, files, (i) => {
        files.splice(i, 1);
        render();
      });
      $go.disabled = files.length === 0;
    }

    async function add(fl) {
      for (const f of fl) {
        $status.textContent = `Envoi de ${f.name}…`;
        try {
          files.push({name: f.name, path: await uploadFile(f)});
        } catch {
          ui.toast(`Envoi échoué : ${f.name}`, "bad");
          break;
        }
        render();
      }
      $status.textContent = "";
    }

    async function go() {
      if ($go.disabled) return;
      const a = cur();
      store.set(`${p}.action`, a.id);
      if ($opt && a.options) store.set(`${p}.${a.id}`, $opt.value);
      $go.disabled = true;
      let ok = 0;
      for (const f of files) {
        const r = await post("/api/jobs", {
          kind,
          title: `${a.label} : ${f.name.slice(0, 36)}`,
          params: {path: f.path, ...a.params, ...(a.options ? {[a.optKey]: $opt.value} : {})},
        });
        if (r.ok) ok++;
      }
      files.length = 0;
      render();
      $status.textContent = `${ok} tâche(s) lancée(s).`;
    }

    ui.dropzone($(`#${p}-drop`), {multiple: true, onFiles: add});
    $(`#${p}-clear`).onclick = () => {
      files.length = 0;
      render();
    };
    $act.onchange = opts;
    $go.onclick = go;
    jobsView($(`#${p}-result`), (j) => j.kind === kind, {icon: title.icon, title: "Rien pour l'instant", hint: title.hint, limit: 10});
    opts();
    render();
  }

  tab({
    p: "im", kind: "image", title: {icon: "image", hint: "Les images sont enregistrées dans le dossier Atelier › images."},
    actions: [
      {id: "upscale2", label: "Agrandir ×2", params: {action: "upscale", factor: 2}, options: [["photo", "Photo"], ["anime", "Illustration / anime"]], optKey: "style"},
      {id: "upscale4", label: "Agrandir ×4", params: {action: "upscale", factor: 4}, options: [["photo", "Photo"], ["anime", "Illustration / anime"]], optKey: "style"},
      {id: "watermark", label: "Effacer un filigrane (zone)", params: {action: "watermark"}, options: [["br", "Coin bas-droite"], ["bl", "Coin bas-gauche"], ["tr", "Coin haut-droite"], ["tl", "Coin haut-gauche"], ["c", "Centre"]], optKey: "zone"},
      {id: "rembg", label: "Détourer (fond transparent)", params: {action: "rembg"}, options: [["u2net", "Général"], ["isnet-general-use", "Général (précis)"], ["u2net_human_seg", "Personnes"], ["isnet-anime", "Anime"]], optKey: "model"},
    ],
  });
  tab({
    p: "au", kind: "audio", title: {icon: "music", hint: "Les fichiers sont enregistrés dans le dossier Atelier › audio."},
    actions: [
      {id: "stems4", label: "Séparer en 4 pistes", params: {action: "stems", model: "htdemucs"}, options: [["mp3", "MP3"], ["flac", "FLAC"], ["wav", "WAV"]], optKey: "format"},
      {id: "stems2", label: "Voix + accompagnement", params: {action: "stems", model: "htdemucs", two_stems: true}, options: [["mp3", "MP3"], ["flac", "FLAC"], ["wav", "WAV"]], optKey: "format"},
      {id: "denoise", label: "Réduire le bruit (voix)", params: {action: "denoise"}, options: [["wav", "WAV"], ["flac", "FLAC"], ["mp3", "MP3"]], optKey: "format"},
    ],
  });
})();
