(() => {
  const $url = $("#yt-url"), $info = $("#yt-info"), $q = $("#yt-q"), $langs = $("#yt-langs");
  const $pl = $("#yt-pl"), $plw = $("#yt-pl-wrap"), $go = $("#yt-go"), $status = $("#yt-status");
  let current = null;

  const seg = ui.segmented(
    $("#yt-mode"),
    [["video", "Vidéo (mkv)", "youtube"], ["audio", "Audio (mp3)", "play"], ["subs", "Sous-titres seuls", "captions"]],
    store.get("yt.mode", "video"),
    () => sync()
  );
  const mode = () => seg.get();

  function sync() {
    $("#yt-q-wrap").hidden = mode() !== "video";
    $("#yt-l-wrap").hidden = mode() !== "subs";
    store.set("yt.mode", mode());
    store.set("yt.q", $q.value);
    store.set("yt.langs", $langs.value);
  }

  async function probe() {
    const url = $url.value.trim();
    $plw.hidden = true;
    if (!url) return;
    $info.textContent = "Analyse…";
    let r;
    try {
      r = await post("/api/youtube/probe", {url});
    } catch {
      $info.textContent = "Erreur réseau.";
      return;
    }
    const d = await r.json();
    if (!r.ok) {
      $info.textContent = d.detail || "Erreur.";
      return;
    }
    $info.textContent = d.playlist
      ? `Playlist : ${d.title} — ${d.count} vidéos`
      : `Vidéo : ${d.title}${d.uploader ? ` — ${d.uploader}` : ""}`;
    $plw.hidden = !d.playlist;
  }

  async function go() {
    const url = $url.value.trim();
    if (!url) return ($status.textContent = "Saisir une URL.");
    if (current) return;
    sync();
    $go.disabled = true;
    $status.textContent = "En file…";
    const r = await post("/api/jobs", {
      kind: "youtube",
      title: `YouTube ${mode()} : ${url.slice(0, 50)}`,
      params: {url, mode: mode(), quality: $q.value, sub_langs: $langs.value, playlist: !$plw.hidden && $pl.checked},
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
      $status.textContent = {done: "Terminé.", failed: `Échec : ${j.error}`, cancelled: "Annulé."}[j.status];
      current = null;
      $go.disabled = false;
    }
  });

  $q.value = store.get("yt.q", "best");
  $langs.value = store.get("yt.langs", "en");
  $q.onchange = $langs.onchange = sync;
  $("#yt-probe").onclick = probe;
  $url.addEventListener("keydown", (e) => e.key === "Enter" && !e.ctrlKey && probe());
  $url.addEventListener("change", probe);
  $go.onclick = go;
  jobsView($("#yt-result"), (j) => j.kind === "youtube", {icon: "youtube", title: "Rien pour l'instant", hint: "Les téléchargements lancés ici s'affichent avec leur progression."});
  sync();
})();
