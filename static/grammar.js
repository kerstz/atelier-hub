// Correcteur: Harper (WASM, /harper/) pour l'anglais, LanguageTool local (/api/grammar) pour le reste.
(() => {
  const $in = $("#gr-in"), $back = $("#gr-back"), $lang = $("#gr-lang"), $issues = $("#gr-issues");
  const $engine = $("#gr-engine"), $status = $("#gr-status"), $missing = $("#gr-missing");
  const $fix = $("#gr-fix"), $stop = $("#gr-stop");
  const LANGS = [
    ["fr", "Français"], ["en", "English (US)"], ["en-gb", "English (UK)"], ["es", "Español"],
    ["de", "Deutsch"], ["pt", "Português"], ["it", "Italiano"],
  ];
  const DIALECT = {en: "American", "en-gb": "British"};
  let info = null, matches = [], seq = 0, timer = 0, harperLoad = null;
  let ignored = new Set(JSON.parse(store.get("gr.ignore", "[]")));

  const key = (m) => `${m.rule || m.kind}|${$in.value.substr(m.offset, m.length)}`;
  const useHarper = () => !!info?.harper && DIALECT[$lang.value];

  function loadHarper() {
    harperLoad ??= new Promise((ok, ko) => {
      const s = document.createElement("script");
      s.src = "/harper/harper.js";
      s.onload = ok;
      s.onerror = () => ko(new Error("Harper introuvable: ./scripts/build-harper.sh"));
      document.head.append(s);
    });
    return harperLoad;
  }

  function engineLabel() {
    const l = $lang.value;
    if (DIALECT[l] && info?.harper) return "Harper · navigateur";
    return info?.lt_available ? "LanguageTool · local" : "";
  }

  function missingMsg() {
    const l = $lang.value;
    if (DIALECT[l] && info.harper) return "";
    if (info.lt_available) return "";
    return (DIALECT[l] ? "Aucun moteur installé. Anglais : scripts/build-harper.sh — ou pour toutes les langues : " : "LanguageTool n'est pas installé : ") + (info.hint || "");
  }

  function paintBack() {
    const t = $in.value;
    const frag = document.createDocumentFragment();
    let pos = 0;
    for (const [i, m] of matches.entries()) {
      if (m.offset < pos) continue;
      frag.append(t.slice(pos, m.offset));
      const mk = document.createElement("mark");
      mk.className = "gr-" + (m.spell ? "spell" : "gram");
      mk.dataset.i = i;
      mk.textContent = t.substr(m.offset, m.length);
      frag.append(mk);
      pos = m.offset + m.length;
    }
    frag.append(t.slice(pos) + "\n");
    $back.replaceChildren(frag);
    $back.scrollTop = $in.scrollTop;
  }

  function apply(m, rep) {
    const t = $in.value;
    $in.value = t.slice(0, m.offset) + rep + t.slice(m.offset + m.length);
    store.set("gr.text", $in.value);
    run(true);
  }

  function focusMatch(m) {
    $in.focus();
    $in.setSelectionRange(m.offset, m.offset + m.length);
  }

  function card(m) {
    const word = $in.value.substr(m.offset, m.length);
    const c = ui.h("div", "gr-card");
    c.append(ui.h("div", "gr-kind", m.kind || "Grammaire"));
    const line = ui.h("div", "gr-msg");
    line.append(ui.h("span", "gr-bad", word.length > 60 ? word.slice(0, 57) + "…" : word), " — ", m.message || m.short || "");
    c.append(line);
    const acts = ui.h("div", "gr-acts");
    for (const r of m.replacements.slice(0, 4)) {
      const b = ui.h("button", "btn sm primary", r === "" ? "supprimer" : r);
      b.onclick = (e) => (e.stopPropagation(), apply(m, r));
      acts.append(b);
    }
    const ig = ui.h("button", "btn sm ghost", "Ignorer");
    ig.title = "Ne plus signaler ce cas";
    ig.onclick = (e) => {
      e.stopPropagation();
      ignored.add(key(m));
      store.set("gr.ignore", JSON.stringify([...ignored]));
      matches = matches.filter((x) => x !== m);
      paint();
    };
    acts.append(ig);
    c.append(acts);
    c.onclick = () => focusMatch(m);
    return c;
  }

  function paint() {
    paintBack();
    $issues.classList.remove("stale");
    $fix.disabled = !matches.some((m) => m.replacements.length);
    if (!$in.value.trim()) {
      $issues.replaceChildren(ui.h("p", "dim", "Les remarques apparaissent ici."));
      $status.textContent = "";
      return;
    }
    if (!matches.length) {
      $issues.replaceChildren(ui.h("p", "gr-ok", "Rien à signaler."));
      $status.textContent = "";
      return;
    }
    $status.textContent = `${matches.length} ${matches.length > 1 ? "remarques" : "remarque"}`;
    $issues.replaceChildren(...matches.map(card));
  }

  async function check(text) {
    const l = $lang.value;
    if (useHarper()) {
      await loadHarper();
      return (await window.harper.check(text, DIALECT[l])).map((m) => ({...m, spell: /orth|spell/i.test(m.kind)}));
    }
    const r = await post("/api/grammar/check", {text, lang: l});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Vérification impossible");
    return (await r.json()).matches.map((m) => ({...m, spell: /typo|spell|orth/i.test(m.rule + m.kind)}));
  }

  async function run(now) {
    clearTimeout(timer);
    const text = $in.value;
    const mine = ++seq;
    if (!text.trim()) {
      matches = [];
      return paint();
    }
    const go = async () => {
      if (!info) await refreshInfo();
      if (!info || missingMsg()) return;
      $status.textContent = "Vérification…";
      try {
        const ms = await check(text);
        if (mine !== seq || text !== $in.value) return;
        matches = ms.filter((m) => !ignored.has(key(m))).sort((a, b) => a.offset - b.offset);
        paint();
        refreshInfo(true);
      } catch (e) {
        if (mine !== seq) return;
        paint();
        ui.toast(e.message, "bad");
      }
    };
    now ? go() : (timer = setTimeout(go, 700));
  }

  async function refreshInfo(quiet) {
    try {
      info = await (await fetch("/api/grammar/status")).json();
    } catch {
      return;
    }
    $stop.hidden = !info.lt_running;
    if (quiet) return;
    refreshHead();
  }

  function refreshHead() {
    if (!info) return;
    const msg = missingMsg();
    $missing.hidden = !msg;
    $missing.textContent = msg;
    $engine.textContent = engineLabel();
    $engine.hidden = !$engine.textContent;
  }

  $in.addEventListener("input", () => {
    store.set("gr.text", $in.value);
    matches = [];
    paintBack();
    $issues.classList.add("stale");
    run();
  });
  $in.addEventListener("scroll", () => ($back.scrollTop = $in.scrollTop));
  $in.addEventListener("click", () => {
    // clic sur un mot souligné: met la carte en avant
    const p = $in.selectionStart;
    const i = matches.findIndex((m) => p >= m.offset && p <= m.offset + m.length);
    $issues.querySelectorAll(".gr-card").forEach((c, j) => c.classList.toggle("on", j === i));
    if (i >= 0) $issues.children[i]?.scrollIntoView({block: "nearest"});
  });
  $lang.addEventListener("change", () => {
    store.set("gr.lang", $lang.value);
    matches = [];
    paintBack();
    $issues.classList.add("stale");
    refreshHead();
    run(true);
  });
  $("#gr-go").onclick = () => run(true);
  $fix.onclick = () => {
    let t = $in.value, end = Infinity;
    for (const m of [...matches].reverse()) {
      if (!m.replacements.length || m.offset + m.length > end) continue;
      t = t.slice(0, m.offset) + m.replacements[0] + t.slice(m.offset + m.length);
      end = m.offset;
    }
    $in.value = t;
    store.set("gr.text", t);
    run(true);
  };
  $("#gr-copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText($in.value);
      ui.toast("Copié", "ok");
    } catch {
      $in.select();
    }
  };
  $("#gr-clear").onclick = () => {
    $in.value = "";
    store.set("gr.text", "");
    matches = [];
    paint();
    $in.focus();
  };
  $("#gr-reset").onclick = () => {
    ignored = new Set();
    store.set("gr.ignore", "[]");
    run(true);
  };
  $stop.onclick = async () => {
    await post("/api/grammar/stop");
    refreshInfo();
  };

  for (const [v, n] of LANGS) $lang.append(new Option(n, v));
  $lang.value = store.get("gr.lang", "fr");
  if (!$lang.value) $lang.value = "fr";
  $in.value = store.get("gr.text", "");
  paint();

  refreshInfo();
  bus.addEventListener("tab:corriger", async () => {
    await refreshInfo();
    if ($in.value.trim() && !matches.length) run(true);
  });
})();
