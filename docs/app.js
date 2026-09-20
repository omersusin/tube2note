const BACKEND_URL = "https://YOUR-BACKEND"; // agent: set Render/Fly URL, no keys here
const $ = id => document.getElementById(id);
function token() { return (new URLSearchParams(location.search).get("t") || ""); }
async function api(path, body) {
  const o = body === undefined ? {headers: {"X-Token": token()}}
    : {method: "POST", headers: {"Content-Type": "application/json", "X-Token": token()}, body: JSON.stringify(body)};
  const r = await fetch(BACKEND_URL + path, o);
  let j = {}; try { j = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(j.error || j.detail || ("HTTP " + r.status));
  return j;
}
function payload() {
  return {urls: $("urls").value.split(/\s+/).filter(Boolean), name: $("name").value,
    lang: $("lang").value, layout: $("layout").value, max: +$("max").value || 100,
    since: $("since").value, timestamps: $("timestamps").checked, clean: $("clean").checked,
    link_timestamps: $("link_timestamps").checked, srt: $("srt").checked,
    split_words: +$("split").value || 0, workers: +$("workers").value || 1};
}
function render(s) {
  const j = s.job; if (!j) return;
  const p = j.progress, pct = p.total ? Math.round(100 * p.done / p.total) : 0;
  $("bar").value = pct;
  $("nums").textContent = p.total ? p.done + "/" + p.total + " - " + p.words + " words" : j.state;
  $("log").textContent = j.log.join("\n"); $("log").scrollTop = 1e9;
  const f = (s.files || [])[0];
  $("dl").hidden = !f;
  if (f) $("dl").href = BACKEND_URL + "/api/download?path=" + encodeURIComponent(f.path) + (token() ? "&t=" + encodeURIComponent(token()) : "");
}
async function poll() {
  try { render(await api("/api/state")); $("err").textContent = ""; }
  catch (e) { $("err").textContent = e.message; }
  setTimeout(poll, 1500);
}
$("go").onclick = async () => {
  $("err").textContent = ""; $("dl").hidden = true;
  try { render(await api("/api/start", payload())); } catch (e) { $("err").textContent = e.message; }
};
$("local").onclick = () => { location.href = "http://127.0.0.1:8765"; };
poll();
