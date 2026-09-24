/* Transparent signal overlay: active admin signals are informational and clearly separated from market data. */
(() => {
  const isAdmin = location.pathname.includes('enterprise-mdr-admin');
  const isTrader = location.pathname.includes('enterprise-mdr');
  if (!isAdmin && !isTrader) return;
  const css = document.createElement('style');
  css.textContent = `.signal-card{background:#111923;border:1px solid #334154;border-radius:14px;padding:14px;margin:12px 0;color:#eef2f7}.signal-card.demo{border-color:#6b7280}.signal-card.active{border-color:#f0c419;box-shadow:0 0 0 1px #f0c41933}.signal-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}.signal-grid input,.signal-grid select{background:#090d12;border:1px solid #2a3441;border-radius:8px;padding:9px;color:#fff;width:100%}.signal-btn{background:#f0c419;color:#111;border:0;border-radius:8px;padding:9px 12px;font-weight:700;cursor:pointer}.signal-muted{color:#9aa7b6;font-size:12px}.signal-row{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid #263241}`;
  document.head.appendChild(css);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = async (path, options={}) => { const r = await fetch(path,{credentials:'include',headers:{'Content-Type':'application/json',...(options.headers||{})},...options}); if(!r.ok) throw Error(await r.text() || `HTTP ${r.status}`); return r.json(); };
  const mount = (title, html, selector='body') => { const host=document.createElement('section'); host.className='signal-card'; host.innerHTML=`<h2 style="margin:0 0 8px;font-size:18px">${title}</h2>${html}`; document.querySelector(selector)?.prepend(host); return host; };
  const countdown = expires => { const ms = new Date(expires).getTime()-Date.now(); return ms > 0 ? `${Math.ceil(ms/60000)} min left` : 'expired'; };
  function renderUser(host, signals) {
    const active=signals.filter(s=>s.active);
    host.innerHTML = active.length ? active.map(s=>`<div class="signal-row"><div><b>${esc(s.symbol)} ${esc(s.direction)}</b><div class="signal-muted">Admin strategy • ${esc(s.timeframe)} • expires ${esc(countdown(s.expiresAt)}</div></div><span class="signal-btn" style="background:#233044;color:#dbeafe">Informational</span></div>`).join('') : `<div class="signal-muted">No active admin signal. The chart is showing market-data or demo fallback only; it is not a trading recommendation.</div>`;
  }
  async function userPanel() {
    const host=mount('Strategy signals', '<div class="signal-muted">Loading current admin-published signals…</div>');
    const load=async()=>{try{renderUser(host,await api('/api/signals'));}catch(e){host.innerHTML='<div class="signal-muted">Signals unavailable. Chart fallback remains clearly labeled.</div>';}};
    await load(); setInterval(load,15000);
  }
  async function adminPanel() {
    const host=mount('Admin strategy signals', `<p class="signal-muted">Publish time-limited informational signals. These do not execute trades or alter market data.</p><form id="signalForm" class="signal-grid"><input name="symbol" value="BTCUSDT" placeholder="Symbol" required><select name="direction"><option>LONG</option><option>SHORT</option><option>WATCH</option></select><select name="timeframe"><option>15m</option><option>1h</option><option>4h</option></select><input name="durationMinutes" type="number" min="1" max="10080" value="60" placeholder="Minutes" required><input name="note" placeholder="Public note"><button class="signal-btn" type="submit">Publish signal</button></form><div id="signalList" style="margin-top:12px"></div>`);
    const form=host.querySelector('#signalForm'), list=host.querySelector('#signalList');
    const load=async()=>{try{const rows=await api('/api/admin/signals');list.innerHTML=rows.length?rows.map(s=>`<div class="signal-row"><div><b>${esc(s.symbol)} ${esc(s.direction)}</b><div class="signal-muted">${esc(s.timeframe)} • ${esc(s.note||'No note')} • ${esc(countdown(s.expiresAt))}</div></div><button class="signal-btn" data-id="${esc(s.id)}">Expire</button></div>`).join(''):'<div class="signal-muted">No published signals.</div>'; list.querySelectorAll('[data-id]').forEach(b=>b.onclick=async()=>{await api('/api/admin/signals/'+b.dataset.id,{method:'DELETE'});load();});}catch(e){list.textContent='Admin authentication required or API unavailable.';}};
    form.onsubmit=async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(form));payload.durationMinutes=Number(payload.durationMinutes);try{await api('/api/admin/signals',{method:'POST',body:JSON.stringify(payload)});form.reset();load();}catch(e){alert(e.message);}}; await load();
  }
  const boot=()=>isAdmin?adminPanel():userPanel(); if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
