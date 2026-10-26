// The School Expert — small progressive enhancements (site works without JS)
(function(){
  const $ = (s, r=document) => r.querySelector(s), $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
  const burger = $('.burger'); if (burger) burger.addEventListener('click', () => { $('.menu').classList.toggle('open'); burger.setAttribute('aria-expanded', $('.menu').classList.contains('open')); });
  // "Other" option reveal
  $$('[data-other-for]').forEach(inp => {
    const name = inp.dataset.otherFor;
    const sync = () => { const sel = $$(`[name="${name}"]`).some(x => (x.value === '__other' || x.dataset.isOther) && (x.checked || x.selected || (x.tagName === 'SELECT' && x.value === '__other'))); inp.classList.toggle('hidden', !sel && !inp.value); };
    $$(`[name="${name}"]`).forEach(x => x.addEventListener('change', sync)); sync();
  });
  // max selections
  $$('[data-max]').forEach(group => {
    const max = +group.dataset.max, boxes = $$('input[type=checkbox]', group);
    const sync = () => { const n = boxes.filter(b => b.checked).length; boxes.forEach(b => { if (!b.checked) b.disabled = n >= max; }); };
    boxes.forEach(b => b.addEventListener('change', sync)); sync();
  });
  // conditional sections/fields (showIf)
  $$('[data-show-if]').forEach(el => {
    const c = JSON.parse(el.dataset.showIf);
    const sync = () => {
      const inputs = $$(`[name="${c.field}"]`);
      const vals = inputs.filter(x => (x.type === 'checkbox' || x.type === 'radio') ? x.checked : true).map(x => x.value).filter(Boolean);
      const v = vals[0] || '';
      let show = true;
      if ('equals' in c) show = show && v === c.equals;
      if ('notEquals' in c) show = show && v !== c.notEquals;
      if ('in' in c) show = show && c.in.includes(v);
      if ('includesAny' in c) show = show && c.includesAny.some(x => vals.includes(x));
      if (c.notEmpty) show = show && vals.length > 0;
      if ('excludes' in c) show = show && !vals.includes(c.excludes);
      el.classList.toggle('hidden', !show); };
    $$(`[name="${c.field}"]`).forEach(x => x.addEventListener('change', sync)); sync();
  });
  // character counters for fields with a limit from the form document
  $$('[data-maxlength]').forEach(el => { const n = +el.dataset.maxlength, out = document.createElement('div'); out.className = 'help'; el.after(out);
    const upd = () => { out.textContent = `${el.value.length.toLocaleString()} / ${n.toLocaleString()} characters`; out.style.color = el.value.length > n ? 'var(--red)' : ''; };
    el.addEventListener('input', upd); upd(); });
  // repeat groups: show next empty item
  $$('[data-repeat]').forEach(wrap => {
    const items = $$('.repeat-item', wrap), btn = $('.add-item', wrap);
    let shown = Math.max(1, items.filter(i => $$('input,textarea', i).some(x => x.value)).length);
    items.forEach((it, i) => it.classList.toggle('hidden', i >= shown));
    if (btn) { btn.classList.toggle('hidden', shown >= items.length); btn.addEventListener('click', e => { e.preventDefault(); if (shown < items.length) { items[shown].classList.remove('hidden'); shown++; } btn.classList.toggle('hidden', shown >= items.length); }); }
  });
  // confirm buttons
  $$('[data-confirm]').forEach(b => b.addEventListener('click', e => { if (!confirm(b.dataset.confirm)) e.preventDefault(); }));
  // autosave notice for long forms
  const f = $('form[data-autosave]'); if (f) { let dirty = false; f.addEventListener('input', () => dirty = true); f.addEventListener('submit', () => dirty = false); window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } }); }
  // cookie banner
  const cb = $('#cookie'); if (cb) $$('[data-cookie]', cb).forEach(b => b.addEventListener('click', () => {
    const v = b.dataset.cookie; document.cookie = 'tse_cookie_consent=' + v + ';path=/;max-age=' + 60*60*24*180 + ';samesite=lax';
    fetch('/cookie-consent', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded','X-CSRF-Token':cb.dataset.csrf}, body:'choice='+v}).finally(() => location.reload());
  }));
  // copy link
  $$('[data-copy]').forEach(b => b.addEventListener('click', () => { navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied!'; }));
})();

// Installable app (PWA): register the service worker.
if ('serviceWorker' in navigator && location.protocol === 'https:' || location.hostname === 'localhost') {
  window.addEventListener('load', function () { navigator.serviceWorker && navigator.serviceWorker.register('/sw.js').catch(function () {}); });
}

// CSP-safe behaviours (no inline event handlers anywhere: script-src uses per-request nonces)
document.addEventListener('change', e => {
  const t = e.target;
  if (t.matches('[data-autosubmit]')) t.form.submit();
  if (t.matches('[data-switch-org]')) { t.form.action = '/switch-org/' + t.value; t.form.submit(); }
  if (t.matches('[data-toggle-target]')) document.getElementById(t.dataset.toggleTarget).classList.toggle('hidden', t.value !== t.dataset.toggleValue);
  if (t.matches('[data-is-other]')) { const box = t.closest('.field').querySelector('[data-other-for]'); if (box) box.classList.toggle('hidden', !t.checked); }
});
document.addEventListener('click', e => { if (e.target.closest('[data-print]')) { e.preventDefault(); window.print(); } });
