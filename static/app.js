const $ = (s) => document.querySelector(s);
const LABEL = {queued: "En file", running: "En cours", done: "Terminé", failed: "Échec", cancelled: "Annulé"};
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

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function showTab(name) {
  if (!$(`#tab-${name}`)) name = "systeme";
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== `tab-${name}`));
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  location.hash = name;
  if (name === "systeme") refreshSystem();
}

function renderJobs() {
  const ul = $("#joblist");
  ul.replaceChildren();
  [...jobs.values()].sort((a, b) => b.id - a.id).forEach((j) => {
    const li = el("li");
    const top = el("div", null, "row");
    top.append(el("strong", `#${j.id} ${j.title}`), el("span", LABEL[j.status] ?? j.status, `st-${j.status}`));
    li.append(top);
    if (j.status === "running" || j.status === "queued") {
      const bar = el("div", null, "bar");
      const fill = el("div");
      fill.style.width = `${Math.round((j.progress || 0) * 100)}%`;
      bar.append(fill);
      li.append(bar);
    }
    const info = j.error || j.message;
    if (info) li.append(el("div", info, "dim"));
    const btns = el("div", null, "btns");
    if (j.status === "running" || j.status === "queued") {
      const b = el("button", "Annuler");
      b.onclick = () => post(`/api/jobs/${j.id}/cancel`);
      btns.append(b);
    }
    if (j.status === "done" && j.output) {
      const b = el("button", "Ouvrir le dossier");
      b.onclick = () => post(`/api/jobs/${j.id}/open`);
      btns.append(b);
    }
    if (btns.children.length) li.append(btns);
    ul.append(li);
  });
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
  $("#ollama-state").textContent = s.ollama.up ? (s.ollama.models.length ? "" : "Aucun modèle chargé.") : "Ollama injoignable.";
  const ul = $("#models");
  ul.replaceChildren();
  s.ollama.models.forEach((m) => {
    const li = el("li");
    const row = el("div", null, "row");
    row.append(el("span", `${m.name} — ${gib(m.size)} — ${m.gpu_pct} % GPU`));
    const b = el("button", "Décharger");
    b.onclick = async () => {
      b.disabled = true;
      await post("/api/ollama/unload", {model: m.name});
      refreshSystem();
    };
    row.append(b);
    li.append(row);
    ul.append(li);
  });
  $("#gpu-lock").textContent = s.gpu_busy ? "Occupé (une tâche GPU tourne)." : "Libre.";
}

function listen() {
  const es = new EventSource("/api/events");
  es.addEventListener("job", (e) => {
    const j = JSON.parse(e.data);
    jobs.set(j.id, j);
    renderJobs();
    bus.dispatchEvent(new CustomEvent("job", {detail: j}));
  });
  es.addEventListener("delta", (e) => bus.dispatchEvent(new CustomEvent("delta", {detail: JSON.parse(e.data)})));
}

document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
$("#clear").onclick = async () => {
  await post("/api/jobs/clear");
  const list = await (await fetch("/api/jobs")).json();
  jobs.clear();
  list.forEach((j) => jobs.set(j.id, j));
  renderJobs();
};
$("#demo-gpu").onclick = () => post("/api/jobs", {kind: "demo", title: "Test GPU", params: {gpu: true, seconds: 5}});
$("#demo-cpu").onclick = () => post("/api/jobs", {kind: "demo", title: "Test CPU", params: {gpu: false, seconds: 5}});

(async () => {
  const list = await (await fetch("/api/jobs")).json();
  list.forEach((j) => jobs.set(j.id, j));
  renderJobs();
  listen();
  showTab(location.hash.slice(1) || "traduire");
  setInterval(refreshSystem, 2000);
})();
