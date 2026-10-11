(() => {
  const $list = $("#sv-list"), $state = $("#sv-state");
  const busy = new Set();

  async function load() {
    if ($("#tab-services").hidden) return;
    let list;
    try {
      list = await (await fetch("/api/services")).json();
    } catch {
      $state.textContent = "Erreur réseau.";
      return;
    }
    $state.textContent = list.length ? "" : "Aucun service dans config.toml ([services.*]).";
    $list.replaceChildren(...list.map(render));
  }

  function render(s) {
    const li = el("li", null, "sv");
    const left = el("div");
    const dot = el("span", null, "dot" + (s.up ? " up" : ""));
    left.append(dot, el("strong", s.name), el("span", `  :${s.port} — ${s.up ? "actif" : "arrêté"}`, "dim"));
    const right = el("div", null, "btns");
    if (/^https?:\/\//.test(s.url)) {
      const a = el("a", "Ouvrir", s.up ? "" : "off");
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener";
      right.append(a);
    }
    if (s.control) {
      const b = el("button", s.up ? "Arrêter" : "Démarrer");
      b.disabled = busy.has(s.id);
      b.onclick = () => act(s, b);
      right.append(b);
    }
    li.append(left, right);
    return li;
  }

  async function act(s, b) {
    const want = !s.up;
    busy.add(s.id);
    b.disabled = true;
    $state.textContent = `${want ? "Démarrage" : "Arrêt"} de ${s.name}…`;
    try {
      const r = await post(`/api/services/${s.id}/${want ? "start" : "stop"}`);
      $state.textContent = r.ok ? "" : (await r.json()).detail || "Échec.";
    } catch {
      $state.textContent = "Erreur réseau.";
    }
    busy.delete(s.id);
    // le port met quelques secondes à (dés)apparaître
    for (let i = 0; i < 10; i++) {
      await load();
      const cur = [...$list.children].find((x) => x.querySelector("strong").textContent === s.name);
      if (cur && cur.querySelector(".dot").classList.contains("up") === want) break;
      await new Promise((ok) => setTimeout(ok, 1000));
    }
  }

  bus.addEventListener("services", load);
  setInterval(load, 5000);
})();
