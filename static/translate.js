(() => {
  const $in = $("#tr-in"), $out = $("#tr-out"), $src = $("#tr-src"), $tgt = $("#tr-tgt");
  const $go = $("#tr-go"), $cancel = $("#tr-cancel"), $status = $("#tr-status"), $gloss = $("#tr-gloss");
  const store = {
    get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
  };
  const bufs = new Map();
  let langs = [], current = null;

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
    if (!text || current) return;
    store.set("tr.src", $src.value);
    store.set("tr.tgt", $tgt.value);
    store.set("tr.gloss", $gloss.value);
    $out.value = "";
    $status.textContent = "En file…";
    setBusy(true);
    const title = `Traduction ${$src.value}→${$tgt.value} : ${text.slice(0, 30)}`;
    const r = await post("/api/jobs", {
      kind: "translate",
      title,
      params: {text, src: $src.value, tgt: $tgt.value, glossary: $gloss.value},
    });
    if (!r.ok) {
      $status.textContent = "Erreur de lancement.";
      setBusy(false);
      return;
    }
    current = (await r.json()).id;
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
    const rows = await (await fetch("/api/translations")).json();
    const ul = $("#tr-hist");
    ul.replaceChildren();
    rows.forEach((h) => {
      const li = el("li");
      li.append(el("div", `${name(h.src)} → ${name(h.tgt)}`, "dim"), el("div", h.source, "clip"), el("div", h.result, "clip dim"));
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
  $cancel.onclick = () => current && post(`/api/jobs/${current}/cancel`);
  $in.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") go();
  });
  $("#tr-swap").onclick = () => {
    if ($src.value === "auto") return;
    [$src.value, $tgt.value] = [$tgt.value, $src.value];
    [$in.value, $out.value] = [$out.value, $in.value];
  };
  $("#tr-copy").onclick = async (e) => {
    try {
      await navigator.clipboard.writeText($out.value);
      e.target.textContent = "Copié";
    } catch {
      $out.select();
      document.execCommand("copy");
    }
    setTimeout(() => (e.target.textContent = "Copier"), 1200);
  };
  $("#tr-hclear").onclick = async () => {
    await post("/api/translations/clear");
    loadHistory();
  };

  (async () => {
    langs = await (await fetch("/api/langs")).json();
    fillLangs();
    loadHistory();
  })();
})();
