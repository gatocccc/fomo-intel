// Shared helpers for Lloyd's Tavern pages: formatting, the four pockets, the regime badge.
// No dependencies. Every function copes with missing fields: the API is young and so is the bot.
window.Lloyd = (() => {
  const ORDER = ["cash", "majors", "established", "picks"];
  const POCKETS = {
    cash: {name: "Cash", short: "Cash", cls: "pk-cash"},
    majors: {name: "Majors", short: "Majors", cls: "pk-majors"},
    established: {name: "Established memes", short: "Est. memes", cls: "pk-established"},
    picks: {name: "Picks", short: "Picks", cls: "pk-picks"},
  };
  const REGIME = {risk_on: "Constructive", neutral: "Neutral", risk_off: "Defensive"};
  const REGIME_HINT = {
    risk_on: "Most of the book is working.",
    neutral: "Selective: some pockets on, the rest in cash.",
    risk_off: "SOL is falling hard. Mostly cash; majors shorts once they ship.",
  };

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const num = v => (v == null || v === "" || Number.isNaN(Number(v))) ? null : Number(v);
  const usd = (v, d = 0) => { v = num(v); return v == null ? "—" : (v < 0 ? "−" : "") + "$" + Math.abs(v).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d}); };
  const usdS = (v, d = 0) => { v = num(v); return v == null ? "—" : (v >= 0 ? "+" : "") + usd(v, d); };
  const fmtX = v => { v = num(v); return v == null ? "—" : "x" + v.toFixed(v >= 10 ? 0 : 2); };
  // frac: 0.123 -> "+12.3%". pct: 12.3 -> "12.3%".
  const frac = (v, signed = true) => { v = num(v); return v == null ? "—" : ((signed && v >= 0) ? "+" : "") + (v * 100).toFixed(1) + "%"; };
  const pct = (v, d = 0) => { v = num(v); return v == null ? "—" : v.toFixed(d) + "%"; };
  const when = ts => ts ? new Date(ts * 1000).toLocaleString("en-US", {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"}) : "—";
  const day = ts => ts ? new Date(ts * 1000).toLocaleDateString("en-US", {month: "short", day: "numeric"}) : "—";
  const ago = ts => {
    if (!ts) return "—";
    const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h} h ago`;
    return `${Math.floor(h / 24)} d ago`;
  };
  const hours = h => {
    h = num(h); if (h == null) return "—";
    if (h < 1) return `${Math.round(h * 60)} min`;
    if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0)} h`;
    return `${Math.floor(h / 24)} d ${Math.round(h % 24)} h`;
  };
  const get = url => fetch(url).then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)));
  const post = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})})
    .then(async r => { let d = {}; try { d = await r.json(); } catch (_) { /* no body */ } if (!r.ok) throw new Error(d.error || `Something went wrong (${r.status}).`); return d; });

  // Normalises book.sleeves into the four pockets, in order, with a percentage that adds up to 100 when values exist.
  function sleeves(book) {
    const raw = Array.isArray(book && book.sleeves) ? book.sleeves : [];
    const byKey = Object.fromEntries(raw.filter(s => s && s.key).map(s => [s.key, s]));
    const total = raw.reduce((a, s) => a + (num(s.value_usd) || 0), 0);
    return ORDER.map(k => {
      const s = byKey[k] || {};
      const value = num(s.value_usd);
      let p = num(s.pct);
      if (p == null && value != null && total > 0) p = value / total * 100;
      return {key: k, name: s.name || POCKETS[k].name, cls: POCKETS[k].cls, value_usd: value, pct: p, target_pct: num(s.target_pct), positions: num(s.positions) || 0};
    });
  }

  // Draws the stacked bar into `bar` and, optionally, the legend into `legend`.
  function drawBar(bar, legend, book, opts = {}) {
    const ss = sleeves(book);
    const known = ss.filter(s => s.pct != null);
    bar.innerHTML = "";
    if (!known.length) {
      const s = document.createElement("span"); s.className = "pk-cash"; s.style.width = "100%"; s.title = "No pocket data yet";
      bar.appendChild(s);
    } else {
      ss.forEach(s => {
        if (!s.pct || s.pct <= 0) return;
        const el = document.createElement("span"); el.className = s.cls; el.style.width = Math.max(0, Math.min(100, s.pct)) + "%";
        el.title = `${s.name}: ${pct(s.pct)}${s.value_usd != null ? ` · ${usd(s.value_usd)}` : ""}`;
        bar.appendChild(el);
      });
    }
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", known.length ? "Pockets: " + ss.map(s => `${s.name} ${pct(s.pct)}`).join(", ") : "Pockets: no data yet");
    if (legend) {
      legend.innerHTML = "";
      ss.forEach(s => {
        const li = document.createElement("li");
        const dot = document.createElement("i"); dot.className = s.cls; li.appendChild(dot);
        const t = document.createElement("span"); t.textContent = `${opts.short ? POCKETS[s.key].short : s.name} ${s.pct != null ? pct(s.pct) : "—"}`; li.appendChild(t);
        if (!opts.short && s.value_usd != null) { const sm = document.createElement("small"); sm.textContent = ` · ${usd(s.value_usd)}`; li.appendChild(sm); }
        legend.appendChild(li);
      });
    }
    return ss;
  }

  const pill = key => { const p = POCKETS[key] || {name: key || "—", cls: "pk-cash"}; return `<span class="pill ${p.cls}">${esc(p.short || p.name)}</span>`; };
  const pocketName = key => (POCKETS[key] || {}).name || key || "—";

  // Fills a .regime element from book.regime (or null).
  function regimeBadge(el, r) {
    const state = r && r.state && REGIME[r.state] ? r.state : null;
    el.className = "regime" + (state ? " " + state : "");
    el.textContent = r && r.label ? r.label : (state ? REGIME[state] : "Regime: unknown");
    el.title = state ? REGIME_HINT[state] : "";
    return state;
  }

  return {ORDER, POCKETS, REGIME, REGIME_HINT, esc, num, usd, usdS, fmtX, frac, pct, when, day, ago, hours, get, post, sleeves, drawBar, pill, pocketName, regimeBadge};
})();
