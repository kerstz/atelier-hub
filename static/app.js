const $ = (s) => document.querySelector(s);
const LABEL = {queued: "En file", running: "En cours", done: "Terminé", failed: "Échec", cancelled: "Annulé"};
const STATUS_ICON = {queued: "list", running: "loader", done: "circle-check", failed: "circle-x", cancelled: "square"};
const FINAL = ["done", "failed", "cancelled"];
const jobs = new Map();
const bus = new EventTarget();
const store = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
};

const post = (url, body) =>
  fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body ?? {})});

async function uploadFile(file) {
  const r = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, {method: "POST", body: file});
  if (!r.ok) throw new Error("envoi échoué");
  return (await r.json()).path;
}

const gib = (b) => (b / 2 ** 30).toFixed(1) + " Go";
const el = (tag, text, cls) => ui.h(tag, cls, text);
const tabs = () => [...document.querySelectorAll("#tabs .nav")];

function showTab(name) {
  if (!$(`#tab-${name}`)) name = "traduire";
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== `tab-${name}`));
  tabs().forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("on", on);
    if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  location.hash = name;
  if (name === "systeme") {
    refreshSystem();
    refreshProfile();
    refreshDeps();
    refreshDisk();
  }
  if (name === "services") bus.dispatchEvent(new Event("services"));
}

// ---- jobs (tray + per-tab result cards)

// Hand a finished job's file to the next tool: Sous-titres tab with the path prefilled.
async function chain(j) {
  let f;
  try {
    const r = await fetch(`/api/jobs/${j.id}/file`);
    if (!r.ok) throw new Error();
    f = await r.json();
  } catch {
    return ui.toast("Fichier de la tâche introuvable", "bad");
  }
  location.hash = `soustitres?path=${encodeURIComponent(f.path)}&name=${encodeURIComponent(f.name)}`;
}

// Named glossaries stored server-side (shared by every tab and by the browser fallback window).
function glossaryBar(ta) {
  const label = ta.closest("label");
  if (!label) return;
  const bar = el("div", null, "field-row wrap gloss-bar");
  const sel = el("select");
  sel.setAttribute("aria-label", "Glossaires enregistrés");
  const name = ui.h("input", "field");
  name.type = "text";
  name.size = 16;
  name.maxLength = 60;
  name.placeholder = "nom du glossaire";
  name.setAttribute("aria-label", "Nom du glossaire");
  let list = [];
  const load = async (keep) => {
    try {
      list = await (await fetch("/api/glossaries")).json();
    } catch {
      list = [];
    }
    ui.select(sel, [["", `— glossaires enregistrés (${list.length}) —`], ...list.map((g) => [g.name, g.name])], keep ?? sel.value);
    if (!sel.value) sel.selectedIndex = 0;
  };
  sel.onchange = () => {
    const g = list.find((x) => x.name === sel.value);
    if (!g) return;
    ta.value = g.text;
    name.value = g.name;
    ta.dispatchEvent(new Event("input", {bubbles: true}));
  };
  const save = ui.button("Enregistrer", {size: "sm", icon: "check", onclick: async () => {
    const n = name.value.trim();
    if (!n) return ui.toast("Donner un nom au glossaire", "bad");
    const r = await fetch(`/api/glossaries/${encodeURIComponent(n)}`, {
      method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text: ta.value}),
    });
    if (!r.ok) return ui.toast("Nom invalide (lettres, chiffres, espaces, . ( ) - ')", "bad");
    ui.toast(`Glossaire « ${n} » enregistré`, "ok");
    load(n);
  }});
  const del = ui.button("Supprimer", {size: "sm", icon: "trash", onclick: async () => {
    if (!sel.value) return;
    if (!(await ui.modal({title: "Supprimer le glossaire ?", body: sel.value, confirm: "Supprimer", danger: true}))) return;
    await fetch(`/api/glossaries/${encodeURIComponent(sel.value)}`, {method: "DELETE"});
    load("");
  }});
  const exp = ui.button("Exporter", {size: "sm", icon: "download", onclick: () => {
    if (sel.value) location.href = `/api/glossaries/${encodeURIComponent(sel.value)}/export`;
  }});
  bar.append(sel, name, save, del, exp);
  label.before(bar);
  load("");
}

async function retryJob(j) {
  const r = await post(`/api/jobs/${j.id}/retry`);
  if (r.ok) return ui.toast(`Tâche #${j.id} relancée`, "ok");
  let why = "Relance impossible";
  try {
    why = (await r.json()).detail || why;
  } catch {}
  ui.toast(why, "bad");
}

async function showLog(j) {
  let text = "Journal indisponible.";
  try {
    const r = await fetch(`/api/jobs/${j.id}/log`);
    if (r.ok) text = await r.text();
  } catch {}
  const head = [`#${j.id} ${j.title}`, j.error ? `Erreur : ${j.error}` : "", ""].filter((x, i) => x || i === 2).join("\n");
  ui.viewer({title: `Journal · tâche #${j.id}`, text: head + text});
}

function jobCard(j) {
  const li = el("li", null, `job st-${j.status}`);
  const top = el("div", null, "job-top");
  top.append(
    ui.icon(STATUS_ICON[j.status] ?? "info", j.status === "running" ? "spin" : ""),
    el("span", `#${j.id} ${j.title}`, "job-title clip"),
    el("span", LABEL[j.status] ?? j.status, "badge")
  );
  li.append(top);
  if (j.status === "running" || j.status === "queued") {
    const p = ui.progress(j.status === "queued" ? 0 : j.progress || 0);
    li.append(p.el);
  }
  const info = j.error || j.message;
  if (info) li.append(el("div", info, "dim job-msg"));
  const btns = el("div", null, "btns");
  if (j.status === "running" || j.status === "queued") {
    btns.append(ui.button("Annuler", {variant: "danger", size: "sm", icon: "square", onclick: () => post(`/api/jobs/${j.id}/cancel`)}));
  }
  if (j.status === "done" && j.output) {
    btns.append(ui.button("Ouvrir le dossier", {size: "sm", icon: "folder-open", onclick: () => post(`/api/jobs/${j.id}/open`)}));
  }
  if (j.status === "done" && /\.[A-Za-z0-9]{2,5}$/.test(j.output || "") && j.kind !== "youtube") {
    btns.append(ui.button("Télécharger", {size: "sm", icon: "download", onclick: () => (location.href = `/api/jobs/${j.id}/download`)}));
  }
  if (j.status === "done" && (j.kind === "youtube" || j.kind === "subtitles")) {
    btns.append(ui.button(j.kind === "youtube" ? "Sous-titrer" : "Résumer / retraduire", {size: "sm", icon: "captions", onclick: () => chain(j)}));
  }
  if (j.status === "failed" || j.status === "cancelled") {
    btns.append(ui.button("Relancer", {size: "sm", icon: "play", onclick: () => retryJob(j)}));
  }
  if (FINAL.includes(j.status)) {
    btns.append(ui.button("Journal", {size: "sm", icon: "file-text", onclick: () => showLog(j)}));
  }
  if (btns.children.length) li.append(btns);
  return li;
}

function jobsView(box, filter, {icon = "inbox", title = "Aucun résultat", hint = "", limit = 5} = {}) {
  const render = () => {
    const list = [...jobs.values()].filter(filter).sort((a, b) => b.id - a.id).slice(0, limit);
    if (!list.length) return box.replaceChildren(ui.empty(icon, title, hint));
    const ul = el("ul", null, "list");
    ul.append(...list.map(jobCard));
    box.replaceChildren(ul);
  };
  bus.addEventListener("job", (e) => filter(e.detail) && render());
  bus.addEventListener("jobs", render);
  render();
}

// Streaming markdown summary card appended to a tab; `status` receives progress text.
function summaryPanel(host, status) {
  const out = ui.h("textarea", "field tall");
  out.readOnly = true;
  out.placeholder = "Le résumé apparaît ici.";
  const copyBtn = ui.button("Copier", {size: "sm", icon: "copy"});
  ui.copy(copyBtn, () => out.value);
  const stop = ui.button("Annuler", {variant: "danger", size: "sm", icon: "square", onclick: () => cur && post(`/api/jobs/${cur}/cancel`)});
  stop.hidden = true;
  const head = ui.h("div", "card-head");
  head.append(ui.h("h2", null, "Résumé"), stop, copyBtn);
  const card = ui.card(head, out);
  card.classList.add("summary");
  card.hidden = true;
  host.append(card);
  let cur = null;

  bus.addEventListener("delta", (e) => {
    if (e.detail.id !== cur) return;
    out.value += e.detail.text;
    out.scrollTop = out.scrollHeight;
  });
  bus.addEventListener("job", async (e) => {
    const j = e.detail;
    if (j.id !== cur) return;
    if (j.status === "running" || j.status === "queued") return status(j.message || "En cours…");
    stop.hidden = true;
    cur = null;
    status({done: "Résumé terminé.", failed: `Échec : ${j.error}`, cancelled: "Annulé."}[j.status]);
    if (j.status === "done") {
      const r = await fetch(`/api/jobs/${j.id}/result`);
      if (r.ok) out.value = await r.text();
    }
  });

  return async (params, title) => {
    if (cur) return false;
    const r = await post("/api/jobs", {kind: "summary", title, params});
    if (!r.ok) {
      ui.toast("Erreur de lancement", "bad");
      return false;
    }
    cur = (await r.json()).id;
    settle(cur);
    out.value = "";
    card.hidden = false;
    stop.hidden = false;
    status("En file…");
    return true;
  };
}

let seen = new Set();
const cards = new Map();
const trayFilter = () => $("#tray-filter")?.value || "all";
const showInTray = (j) => {
  const f = trayFilter();
  return f === "all" || (f === "active" ? !FINAL.includes(j.status) : j.status === "failed");
};
function trayBadge() {
  const active = [...jobs.values()].filter((j) => !FINAL.includes(j.status)).length;
  const badge = $("#tray-count");
  badge.hidden = !active;
  badge.textContent = active;
}

// Full rebuild (initial load / resync / clear).
function renderJobs() {
  const ul = $("#joblist");
  const all = [...jobs.values()].sort((a, b) => b.id - a.id);
  const shown = all.filter(showInTray);
  cards.clear();
  const lis = shown.map((j) => {
    const li = jobCard(j);
    cards.set(j.id, li);
    return li;
  });
  ul.replaceChildren(...lis);
  if (!shown.length) ul.append(ui.empty("inbox", all.length ? "Aucune tâche dans ce filtre" : "Aucune tâche", "Les traductions et téléchargements apparaissent ici."));
  trayBadge();
}

// One event = one card touched (progress arrives several times a second).
function upsertJob(j) {
  const ul = $("#joblist");
  if (!showInTray(j)) {
    cards.get(j.id)?.remove();
    cards.delete(j.id);
    return trayBadge();
  }
  const li = jobCard(j);
  const old = cards.get(j.id);
  if (old?.isConnected) old.replaceWith(li);
  else {
    ul.querySelector(".empty")?.remove();
    const next = [...cards.entries()].filter(([id, c]) => id < j.id && c.isConnected).sort((a, b) => b[0] - a[0])[0];
    if (next) next[1].before(li);
    else ul.append(li);
  }
  cards.set(j.id, li);
  trayBadge();
}

// Job already finished by the time we learn its id (event raced the POST response): apply the end state now.
function settle(id) {
  const j = jobs.get(id);
  if (j && FINAL.includes(j.status)) bus.dispatchEvent(new CustomEvent("job", {detail: j}));
}

function setTray(open) {
  const t = $("#tray");
  t.dataset.open = open ? "1" : "0";
  $("#tray-head").setAttribute("aria-expanded", String(open));
  store.set("tray", open ? "1" : "");
}

function onJob(j, initial = false) {
  const prev = jobs.get(j.id);
  jobs.set(j.id, j);
  if (!initial) {
    if (!prev && !seen.has(j.id)) setTray(true);
    if (prev && !FINAL.includes(prev.status) && FINAL.includes(j.status)) {
      const t = j.title.slice(0, 50);
      if (j.status === "done") ui.toast(`Terminé : ${t}`, "ok");
      else if (j.status === "failed") ui.toast(`Échec : ${t}`, "bad", 7000);
      const live = $("#sr-live");
      if (live && j.status !== "cancelled") live.textContent = `${j.status === "done" ? "Terminé" : "Échec"} : ${t}`;
    }
  }
  seen.add(j.id);
}

// ---- système

async function refreshProfile(refresh = false) {
  let d;
  try {
    d = await (await fetch(`/api/profile${refresh ? "?refresh=true" : ""}`)).json();
  } catch {
    return;
  }
  const p = d.profile, r = d.recommendation;
  const gpu = p.gpu ? `${p.gpu.vendor.toUpperCase()} ${gib(p.gpu.vram_total)} (${gib(p.gpu.vram_free)} libres)` : "aucun GPU exploitable";
  $("#hw-sum").textContent = `${r.label} — ${gpu} · RAM ${gib(p.ram_total)} · ${p.cores} cœurs${p.avx2 ? " · AVX2" : ""}.`;
  const rows = [
    `Moteur de traduction utilisé : ${d.engine === "ctranslate2" ? "NLLB (CTranslate2, CPU)" : "Ollama"} — réglage « ${d.configured} »`,
    `Modèles recommandés : traduction ${r.models.translate || "—"} · texte ${r.models.second || "—"} · vision ${r.models.vision || "indisponible"}`,
  ];
  if (r.engine === "ctranslate2" && !d.ct2_ready) rows.push("Modèle NLLB absent : voir install.sh --engine=ct2");
  d.missing_models.forEach((m) => rows.push(`Modèle absent : ollama pull ${m}`));
  r.notes.forEach((n) => rows.push(n));
  $("#hw").replaceChildren(...rows.map((t) => el("li", t)));
}

async function refreshDeps() {
  const ul = $("#deps");
  if (!ul.children.length) ul.replaceChildren(ui.skeleton(3));
  let rows;
  try {
    rows = await (await fetch("/api/deps")).json();
  } catch {
    return;
  }
  const bad = rows.filter((r) => !r.ok).length;
  $("#deps-sum").textContent = bad ? `${bad} élément(s) manquant(s) sur ${rows.length}.` : `Tout est en place (${rows.length}).`;
  ul.replaceChildren(
    ...rows.map((r) => {
      const li = el("li");
      li.append(ui.icon(r.ok ? "circle-check" : "circle-x"));
      const body = el("div");
      body.append(el("strong", r.label), el("span", ` — ${r.detail}`, "dim"), el("div", `utile pour : ${r.used_by}`, "used"));
      li.append(body);
      if (r.hint) {
        const h = el("div", null, "hint");
        h.append(el("code", r.hint));
        const c = ui.button("Copier", {size: "sm", icon: "copy"});
        ui.copy(c, () => r.hint);
        h.append(c);
        li.append(h);
      }
      return li;
    })
  );
}

const mib = (b) => (b >= 2 ** 30 ? `${(b / 2 ** 30).toFixed(1)} Go` : `${Math.round(b / 2 ** 20)} Mo`);
async function refreshDisk() {
  let d;
  try {
    d = await (await fetch("/api/disk")).json();
  } catch {
    return;
  }
  $("#disk-sum").textContent = `Libre : ${gib(d.free)} sur ${gib(d.total)}.`;
  $("#disk").replaceChildren(
    ...d.items.map((it) => {
      const li = el("li");
      const row = el("div", null, "row");
      row.append(el("span", `${it.label} — ${mib(it.bytes)}`));
      if (it.clean && it.bytes) {
        row.append(ui.button("Vider", {size: "sm", icon: "trash", onclick: async () => {
          const r = await post(`/api/disk/clean/${it.id}`);
          if (r.ok) ui.toast(`${mib((await r.json()).freed)} libérés`, "ok");
          refreshDisk();
        }}));
      }
      li.append(row);
      return li;
    })
  );
}

async function refreshSystem() {
  if ($("#tab-systeme").hidden) return;
  let s;
  try {
    s = await (await fetch("/api/system")).json();
  } catch {
    return;
  }
  const v = s.vram;
  if (v) {
    $("#vram-fill").style.width = `${(100 * v.used) / v.total}%`;
    const busy = v.busy != null ? ` — charge ${v.busy} %` : "";
    $("#vram-text").textContent = `${gib(v.used)} / ${gib(v.total)} (${v.card})${busy}`;
  } else {
    $("#vram-fill").style.width = "0";
    $("#vram-text").textContent = "GPU introuvable (sysfs amdgpu)";
  }
  const st = $("#ollama-state");
  st.replaceChildren();
  if (!s.ollama.up) st.append(ui.empty("alert", "Ollama injoignable", "Vérifier que le service ollama tourne."));
  else if (!s.ollama.models.length) st.append(ui.empty("inbox", "Aucun modèle chargé", "Un modèle se charge à la première traduction."));
  const ul = $("#models");
  ul.replaceChildren();
  s.ollama.models.forEach((m) => {
    const li = el("li");
    const row = el("div", null, "row");
    row.append(el("span", `${m.name} — ${gib(m.size)} — ${m.gpu_pct} % GPU`));
    row.append(
      ui.button("Décharger", {size: "sm", icon: "power", onclick: async (e) => {
        e.currentTarget.disabled = true;
        await post("/api/ollama/unload", {model: m.name});
        refreshSystem();
      }})
    );
    li.append(row);
    ul.append(li);
  });
  $("#gpu-lock").textContent = s.gpu_busy ? "Occupé : une tâche GPU tourne." : "Libre.";
}

// (Re)load the job list: first load, and after any SSE (re)connection so a dropped stream or a
// restarted service never leaves stale "En cours" cards. Changed jobs are replayed as "job" events.
async function resync() {
  let list;
  try {
    list = await (await fetch("/api/jobs")).json();
  } catch {
    return;
  }
  const before = new Map(jobs);
  jobs.clear();
  list.forEach((j) => onJob(j, true));
  renderJobs();
  bus.dispatchEvent(new Event("jobs"));
  list.forEach((j) => {
    const p = before.get(j.id);
    if (p && (p.status !== j.status || p.progress !== j.progress)) bus.dispatchEvent(new CustomEvent("job", {detail: j}));
  });
}

function listen() {
  const es = new EventSource("/api/events");
  es.onopen = resync;
  es.addEventListener("job", (e) => {
    const j = JSON.parse(e.data);
    onJob(j);
    upsertJob(j);
    bus.dispatchEvent(new CustomEvent("job", {detail: j}));
  });
  es.addEventListener("delta", (e) => bus.dispatchEvent(new CustomEvent("delta", {detail: JSON.parse(e.data)})));
}

// ---- shell: theme, sidebar, shortcuts

function effectiveTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
}

function paintThemeButton() {
  const b = $("#theme");
  b.replaceChildren(ui.icon(effectiveTheme() === "dark" ? "sun" : "moon"), el("span", effectiveTheme() === "dark" ? "Thème clair" : "Thème sombre", "lbl"));
}

function setSidebar(collapsed) {
  if (collapsed) document.documentElement.dataset.sb = "1";
  else delete document.documentElement.dataset.sb;
  store.set("sb", collapsed ? "1" : "");
  const b = $("#collapse");
  b.title = collapsed ? "Déployer la barre latérale" : "Réduire la barre latérale";
}

function shortcuts(e) {
  if (e.key === "Escape") {
    if (ui.dismiss()) return;
    if ($("#tray").dataset.open === "1") setTray(false);
    return;
  }
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  if (e.key === "Enter") {
    const b = document.querySelector(".tab:not([hidden]) [data-main]");
    if (b && !b.disabled && !b.hidden) {
      e.preventDefault();
      b.click();
    }
  } else if (/^[1-9]$/.test(e.key)) {
    const t = tabs()[Number(e.key) - 1];
    if (t) {
      e.preventDefault();
      showTab(t.dataset.tab);
    }
  }
}

ui.iconize();
ui.disclosure && document.querySelectorAll("details.adv").forEach(ui.disclosure);
tabs().forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
$("#theme").onclick = () => {
  const next = effectiveTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store.set("theme", next);
  paintThemeButton();
};
$("#collapse").onclick = () => setSidebar(document.documentElement.dataset.sb !== "1");
setSidebar(document.documentElement.dataset.sb === "1");
paintThemeButton();
$("#tray-head").onclick = () => setTray($("#tray").dataset.open !== "1");
setTray(false);
document.addEventListener("keydown", shortcuts);
$("#clear").onclick = async () => {
  await post("/api/jobs/clear");
  const list = await (await fetch("/api/jobs")).json();
  jobs.clear();
  list.forEach((j) => jobs.set(j.id, j));
  renderJobs();
  bus.dispatchEvent(new Event("jobs"));
};
$("#lang-toggle .lbl").textContent = i18n.lang === "en" ? "Français" : "English";
$("#lang-toggle").onclick = i18n.toggle;
$("#hw-refresh").onclick = () => refreshProfile(true);
$("#deps-refresh").onclick = refreshDeps;
$("#tray-filter").onchange = renderJobs;
$("#demo-gpu").onclick = () => post("/api/jobs", {kind: "demo", title: "Test GPU", params: {gpu: true, seconds: 5}});
$("#demo-cpu").onclick = () => post("/api/jobs", {kind: "demo", title: "Test CPU", params: {gpu: false, seconds: 5}});

// #tab ou #tab?text=…&url=… (lanceur desktop, actions du presse-papiers) -> prefill des onglets
function route() {
  const [name, qs] = location.hash.slice(1).split("?");
  const params = new URLSearchParams(qs || "");
  showTab(name || "traduire");
  if (![...params].length) return;
  const fire = () => bus.dispatchEvent(new CustomEvent("prefill", {detail: {tab: name, params}}));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fire, {once: true});
  else fire();
}
window.addEventListener("hashchange", route);
route();
(async () => {
  $("#joblist").append(ui.skeleton(2));
  try {
    const list = await (await fetch("/api/jobs")).json();
    list.forEach((j) => onJob(j, true));
  } catch {}
  renderJobs();
  bus.dispatchEvent(new Event("jobs"));
  listen();
  setInterval(refreshSystem, 2000);
})();
