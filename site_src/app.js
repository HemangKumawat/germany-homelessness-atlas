// Germany Atlas client: search, keyboard, map. No framework.
(() => {
  const B = document.body.dataset.base || ".";
  const $ = (s) => document.querySelector(s);
  const q = $("#q"), res = $("#results");
  let idx = null, sel = -1, hits = [];
  const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ß/g, "ss");
  async function load() { if (!idx) { idx = await (await fetch(B + "/data/search.json")).json(); idx.forEach(r => r.f = fold(r.t + " " + r.b)); } return idx; }
  function render() {
    res.innerHTML = hits.map((h, i) => `<a href="${B}/${h.u}" class="${i === sel ? "sel" : ""}"><span class="k">${h.k}</span>${h.t}</a>`).join("") || '<a class="dim">no match</a>';
    res.style.display = q.value ? "block" : "none";
    const s = res.querySelector(".sel"); if (s) s.scrollIntoView({ block: "nearest" });
  }
  q && q.addEventListener("input", async () => {
    const terms = fold(q.value).split(/\s+/).filter(Boolean); const d = await load();
    hits = terms.length ? d.filter(r => terms.every(t => r.f.includes(t))).slice(0, 40) : []; sel = hits.length ? 0 : -1; render();
  });
  q && q.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) { sel = Math.min(sel + 1, hits.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter" && hits[sel]) location.href = B + "/" + hits[sel].u;
    else if (e.key === "Escape") { q.value = ""; res.style.display = "none"; q.blur(); }
  });
  let g = false;
  document.addEventListener("keydown", (e) => {
    const t = e.target.tagName; if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") { q.focus(); e.preventDefault(); return; }
    if (e.key === "?") { $("#help").classList.toggle("on"); return; }
    if (e.key === "Escape") { $("#help").classList.remove("on"); return; }
    if (g) { g = false; const m = { h: "index.html", p: "places.html", o: "orgs.html", l: "laws.html", s: "sources.html" }[e.key]; if (m) location.href = B + "/" + m; return; }
    if (e.key === "g") { g = true; setTimeout(() => g = false, 1200); return; }
    if (window.atlasMap) window.atlasMap.key(e);
  });

  // ---------------------------------------------------------------- map
  const el = document.getElementById("map"); if (!el || !window.L) return;
  const PAL = ["#2a2f4a", "#3d59a1", "#7aa2f7", "#bb9af7", "#e0af68", "#f7768e"];
  const map = L.map(el, { zoomSnap: .25, keyboard: true }).setView([51.2, 10.4], 5.75);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Grenzen &copy; <a href="https://www.bkg.bund.de">BKG</a> (2026) <a href="https://www.govdata.de/dl-de/by-2-0">dl-de/by-2-0</a> · Zahlen: Destatis' }).addTo(map);
  const obs = JSON.parse(document.getElementById("obs-data").textContent);
  const geo = {}; let level = "land", layer = null; const msel = $("#metric");
  function key() { return msel.value; }
  function scale(vals) { const v = vals.filter(x => x != null).sort((a, b) => a - b); if (!v.length) return () => null;
    const br = [1, 2, 3, 4, 5].map(i => v[Math.min(v.length - 1, Math.floor(i * v.length / 6))]);
    return (x) => x == null ? null : PAL[br.filter(b => x >= b).length]; }
  async function draw() {
    if (!geo[level]) geo[level] = await (await fetch(`${B}/data/geo-${level}.json`)).json();
    const data = (obs[key()] || {})[level] || {};
    const col = scale(Object.values(data).map(d => d.v));
    if (layer) layer.remove();
    layer = L.geoJSON(geo[level], {
      style: f => { const d = data[f.properties.ags]; const c = d ? col(d.v) : null;
        return { color: d ? "#7aa2f7" : "#414868", weight: d ? 1 : .6, dashArray: d ? null : "2 3", fillColor: c || "#000", fillOpacity: c ? .7 : 0 }; },
      onEachFeature: (f, ly) => { const d = data[f.properties.ags];
        ly.bindTooltip(`<b>${f.properties.name}</b> <span class="dim">${f.properties.ags}</span><br>` + (d ? `<span style="color:#e0af68">${d.s}</span>${d.e ? ' <span class="est">†</span>' : ""}` : '<span class="dim">keine Daten</span>'), { className: "tip", sticky: true });
        ly.on("click", () => location.href = `${B}/place/${f.properties.ags}.html`); }
    }).addTo(map);
    const n = Object.keys(data).length, tot = geo[level].features.length;
    $("#cov").textContent = `${n}/${tot} ${level === "land" ? "Länder" : "Kreise"} mit Daten`;
    $("#legend").innerHTML = n ? PAL.slice(1).map(c => `<i style="background:${c}"></i>`).join("") + ' <span class="dim">niedrig → hoch · gestrichelt = keine Daten</span>' : '<span class="dim">keine Daten auf dieser Ebene</span>';
    document.querySelectorAll("[data-level]").forEach(b => b.setAttribute("aria-pressed", b.dataset.level === level));
  }
  document.querySelectorAll("[data-level]").forEach(b => b.addEventListener("click", () => { level = b.dataset.level; draw(); }));
  msel.addEventListener("change", draw);
  window.atlasMap = { key: (e) => {
    if (e.key === "l") { level = "land"; draw(); } else if (e.key === "k") { level = "kreis"; draw(); }
    else if (e.key === "+" || e.key === "=") map.zoomIn(); else if (e.key === "-") map.zoomOut();
    else if (e.key === "0") map.setView([51.2, 10.4], 5.75); } };
  draw();
})();
