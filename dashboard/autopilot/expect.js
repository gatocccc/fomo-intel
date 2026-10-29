// "What to expect": the risk dial talks to /api/expect and shows an honest range, not a promise.
// Expect.mount({radios | select, box, note, onChange}) -> {refresh, value}
//   radios: NodeList/array of <input type=radio name=risk value=20|35|50>, or
//   select: a <select> whose value is the risk percentage.
//   box: element that receives the two horizon cards. note: element for the preliminary line.
window.Expect = (() => {
  const fmtX = v => (v == null || Number.isNaN(Number(v))) ? "—" : "x" + Number(v).toFixed(2);
  const pct = v => (v == null || Number.isNaN(Number(v))) ? "—" : Math.round(Number(v) * 100) + "%";
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

  function render(d, box, note, risk) {
    const hs = Array.isArray(d.horizons) ? d.horizons : [];
    const limit = d.risk != null ? d.risk : risk;
    const cards = hs.map(h => {
      const lim = h.prob_hit_limit;
      return `<div class="ex">
        <h4>In ${esc(h.days)} days</h4>
        <div class="med">${fmtX(h.median_mult)}<small>most likely</small></div>
        <div class="rng">Usual range ${fmtX(h.p10_mult)} to ${fmtX(h.p90_mult)}<br><span style="font-weight:400">(1 in 10 ends below, 1 in 10 ends above)</span></div>
        <div class="lim">Chance of touching your ${esc(limit)}% limit: <b>${pct(lim)}</b></div>
      </div>`;
    }).join("");
    const exp = d.exposure_pct != null ? `<p class="ex-line">At this level about ${esc(Math.round(d.exposure_pct))}% of your money follows the book; the rest sits in USDC.</p>` : "";
    box.innerHTML = (exp + (cards ? `<div class="ex-grid">${cards}</div>` : `<p class="ex-empty">No estimate for this level yet.</p>`));
    if (note) {
      const n = d.based_on_trades != null ? d.based_on_trades : null;
      const base = d.preliminary || n == null || n < 30
        ? `Preliminary. Built from ${n == null ? "very few" : n} real closed trade${n === 1 ? "" : "s"} plus starting assumptions, so treat it as a sketch, not a forecast. It recalculates itself as Lloyd trades.`
        : `Based on ${n} real closed trades. Past results do not promise future ones.`;
      note.textContent = d.note ? `${base} ${d.note}` : base;
    }
  }

  function mount({radios, select, box, note, onChange}) {
    let t = null, seq = 0;
    const list = radios ? Array.from(radios) : [];
    const value = () => {
      if (select) return select.value;
      const c = list.find(r => r.checked);
      return c ? c.value : (list[0] ? list[0].value : "35");
    };
    const update = () => {
      const risk = value();
      onChange && onChange(risk);
      clearTimeout(t);
      const id = ++seq;
      box.setAttribute("aria-busy", "true");
      t = setTimeout(() => fetch(`/api/expect?risk=${encodeURIComponent(risk)}`)
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
        .then(d => { if (id !== seq) return; render(d, box, note, risk); })
        .catch(() => {
          if (id !== seq) return;
          box.innerHTML = `<p class="ex-empty">Could not load the estimate right now. Try again in a minute.</p>`;
          if (note) note.textContent = "";
        })
        .finally(() => { if (id === seq) box.removeAttribute("aria-busy"); }), 150);
    };
    list.forEach(r => r.addEventListener("change", update));
    if (select) select.addEventListener("change", update);
    update();
    return {refresh: update, value};
  }

  return {mount, fmtX, pct};
})();
