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

  // Risk dial cards. Names, exposure and blurbs come from /api/config.risk_levels; these are the fallbacks.
  const FALLBACK_LEVELS = [
    {pct: 20, key: "quiet", name: "Quiet corner", exposure_pct: null, blurb: "You would rather sleep than win big."},
    {pct: 35, key: "regular", name: "Regular's stool", exposure_pct: null, blurb: "The house setting."},
    {pct: 50, key: "loud", name: "Loud table", exposure_pct: null, blurb: "You accept losing half for the full ride."},
  ];
  // dialCards(levels, box, inputName, checkedPct, {static}) -> NodeList of the radios. static: display only, not a form control.
  function dialCards(levels, box, name, checked, opts = {}) {
    const list = Array.isArray(levels) && levels.length ? levels : FALLBACK_LEVELS;
    box.innerHTML = "";
    list.forEach(l => {
      const lab = document.createElement(opts.static ? "div" : "label"); lab.className = "dial";
      const inp = document.createElement("input"); inp.type = "radio"; inp.name = name; inp.value = l.pct;
      inp.checked = String(l.pct) === String(checked); if (opts.static) { inp.disabled = true; inp.tabIndex = -1; }
      const inn = document.createElement("div"); inn.className = "in";
      const b = document.createElement("b"); b.textContent = l.name || l.key || `${l.pct}%`;
      const dd = document.createElement("div"); dd.className = "dd"; dd.textContent = `−${l.pct}%`;
      const sm = document.createElement("small"); sm.textContent = "biggest drop you accept"; dd.appendChild(sm);
      const xp = document.createElement("div"); xp.className = "xp"; xp.textContent = l.exposure_pct != null ? `${Math.round(l.exposure_pct)}% of your money follows the book` : "exposure set by the house";
      const p = document.createElement("p"); p.textContent = l.blurb || "";
      inn.append(b, dd, xp, p); lab.append(inp, inn); box.appendChild(lab);
    });
    return box.querySelectorAll("input[type=radio]");
  }

  // ----- the notebook (/api/lab) -----
  const LAB_LABEL = {testing: "Testing now", watch: "Promising", adopted: "Learned, in use", queued: "Up next", rejected: "Tested, discarded"};
  const labTested = c => c ? (Number(c.adopted) || 0) + (Number(c.rejected) || 0) + (Number(c.watch) || 0) : null;
  // Fills a counter strip: <ul> with three <li>s.
  function labCounts(ul, d) {
    let c = (d && d.counts) || null;
    const ex = d && Array.isArray(d.experiments) ? d.experiments : [];
    if (!c && ex.length) { c = {}; ex.forEach(x => { c[x.status] = (c[x.status] || 0) + 1; }); }
    const items = [[labTested(c), "ideas tested"], [c ? Number(c.adopted) || 0 : null, "in use"], [c ? Number(c.queued) || 0 : null, "up next"]];
    ul.innerHTML = items.map(([n, t]) => `<li><b>${n == null ? "—" : n}</b><span>${t}</span></li>`).join("");
  }
  // One experiment card. Pocket is optional.
  function labCard(x) {
    const st = LAB_LABEL[x.status] ? x.status : "queued";
    const label = x.status_label || LAB_LABEL[st];
    return `<article class="lab-card st-${st}">
      <div class="lab-top"><span class="lab-pill st-${st}">${esc(label)}</span>${x.pocket ? pill(x.pocket) : ""}</div>
      <h3>${esc(x.title)}</h3>
      ${x.hypothesis ? `<p class="hyp"><b>The idea:</b> ${esc(x.hypothesis)}</p>` : ""}
      ${x.conclusion ? `<p class="concl"><b>${st === "adopted" ? "What Lloyd learned:" : "So far:"}</b> ${esc(x.conclusion)}</p>` : ""}
      ${x.date ? `<time>${esc(x.date)}</time>` : ""}
    </article>`;
  }

  return {ORDER, POCKETS, REGIME, REGIME_HINT, esc, num, usd, usdS, fmtX, frac, pct, when, day, ago, hours, get, post, sleeves, drawBar, pill, pocketName, regimeBadge, dialCards, LAB_LABEL, labTested, labCounts, labCard};
})();
