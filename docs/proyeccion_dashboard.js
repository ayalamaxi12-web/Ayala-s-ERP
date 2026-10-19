/*!
 * Proyección de Compras e Inversión 2027 — componente de dashboard (solo lectura)
 * Global Electronics Argentina
 *
 * Sin dependencias. Un solo archivo. Se monta en cualquier contenedor:
 *
 *   ProyeccionDashboard.mount(document.getElementById('app'), data);          // data = objeto del contrato (ver dashboard_data.json)
 *   ProyeccionDashboard.mountFromUrl(el, '/api/proyeccion-2027/dashboard');   // lo trae por fetch
 *
 * Opciones (tercer argumento): { theme: 'auto'|'light'|'dark', onNavigate(tab), title }
 * El componente NO escribe nada: no llama a ningún endpoint salvo el de lectura de mountFromUrl.
 */
(function (global) {
  'use strict';
  var VERSION = '1.1';

  // ------------------------------------------------------------------ utilidades
  var nfInt = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });
  var nf1 = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  var nf2 = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function fInt(v) { return isNum(v) ? nfInt.format(v) : '–'; }
  function f1(v) { return isNum(v) ? nf1.format(v) : '–'; }
  function f2(v) { return isNum(v) ? nf2.format(v) : '–'; }
  function fPct(v, d) { return isNum(v) ? (v * 100).toFixed(d == null ? 0 : d).replace('.', ',') + '%' : '–'; }
  function fUsd(v) { return isNum(v) ? 'US$ ' + nfInt.format(v) : '–'; }
  function fUsdC(v) {  // compacto: US$ 3,85 M / US$ 640 mil
    if (!isNum(v)) return '–';
    var a = Math.abs(v), s = v < 0 ? '-' : '';
    if (a >= 1e6) return s + 'US$ ' + nf2.format(a / 1e6) + ' M';
    if (a >= 1e3) return s + 'US$ ' + nfInt.format(a / 1e3) + ' mil';
    return s + 'US$ ' + nfInt.format(a);
  }
  function fMes(m) {  // '2026-10' -> 'oct-26'
    if (!m || typeof m !== 'string') return m == null ? '' : String(m);
    var p = m.split('-'); if (p.length < 2) return m;
    return MES[parseInt(p[1], 10) - 1] + '-' + p[0].slice(2);
  }
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'text') e.textContent = attrs[k];
      else if (k.slice(0, 2) === 'on' && typeof attrs[k] === 'function') e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    }
    if (kids != null) (Array.isArray(kids) ? kids : [kids]).forEach(function (c) {
      if (c == null) return; e.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
    });
    return e;
  }
  var SVGNS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, kids) {
    var e = document.createElementNS(SVGNS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (kids) (Array.isArray(kids) ? kids : [kids]).forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }
  function find(arr, pred) { for (var i = 0; i < arr.length; i++) if (pred(arr[i])) return arr[i]; return null; }
  function sum(arr) { return arr.reduce(function (a, b) { return a + (isNum(b) ? b : 0); }, 0); }
  function downloadCsv(name, cols, rows) {
    var esc = function (v) { v = v == null ? '' : String(v); return /[;"\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var out = [cols.map(function (c) { return esc(c.label); }).join(';')];
    rows.forEach(function (r) { out.push(cols.map(function (c) { var v = c.val(r); return esc(isNum(v) ? String(v).replace('.', ',') : v); }).join(';')); });
    var blob = new Blob(['\ufeff' + out.join('\n')], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name + '.csv'; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  // ------------------------------------------------------------------ estilos
  var CSS = '' +
  '.pd{--bg:#f4f6fa;--card:#fff;--tx:#1b2433;--mu:#667085;--bd:#dfe3ea;--ac:#2f5597;--ac2:#e8eefb;--good:#2e7d32;--warn:#b26a00;--bad:#c62828;--badbg:#fdecec;--warnbg:#fff4e0;--goodbg:#e8f5e9;' +
  'font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:var(--tx);background:var(--bg);padding:16px;border-radius:10px}' +
  '.pd[data-theme=dark]{--bg:#0f1420;--card:#171e2e;--tx:#e6eaf2;--mu:#9aa5b8;--bd:#2a3347;--ac:#7fa4ee;--ac2:#1d2740;--good:#6fcf7a;--warn:#f2b45a;--bad:#ff8a80;--badbg:#3a1c1f;--warnbg:#3a2c14;--goodbg:#173222}' +
  '@media (prefers-color-scheme:dark){.pd[data-theme=auto]{--bg:#0f1420;--card:#171e2e;--tx:#e6eaf2;--mu:#9aa5b8;--bd:#2a3347;--ac:#7fa4ee;--ac2:#1d2740;--good:#6fcf7a;--warn:#f2b45a;--bad:#ff8a80;--badbg:#3a1c1f;--warnbg:#3a2c14;--goodbg:#173222}}' +
  '.pd *{box-sizing:border-box}.pd h1{font-size:20px;margin:0}.pd h2{font-size:15px;margin:0 0 8px}.pd h3{font-size:13px;margin:0 0 6px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.03em}' +
  '.pd-head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;justify-content:space-between;margin-bottom:10px}.pd-sub{color:var(--mu);font-size:12px}' +
  '.pd-tabs{display:flex;flex-wrap:wrap;gap:4px;border-bottom:1px solid var(--bd);margin-bottom:12px}' +
  '.pd-tab{border:0;background:transparent;color:var(--mu);padding:8px 12px;cursor:pointer;font:inherit;border-bottom:2px solid transparent;margin-bottom:-1px}' +
  '.pd-tab[aria-selected=true]{color:var(--ac);border-color:var(--ac);font-weight:600}' +
  '.pd-grid{display:grid;gap:10px}.pd-kpis{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}.pd-2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}' +
  '.pd-card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px}' +
  '.pd-kpi .v{font-size:22px;font-weight:700;line-height:1.15}.pd-kpi .l{color:var(--mu);font-size:12px;margin-top:2px}.pd-kpi .n{font-size:11px;color:var(--mu);margin-top:4px}' +
  '.pd-kpi.bad .v{color:var(--bad)}.pd-kpi.warn .v{color:var(--warn)}.pd-kpi.good .v{color:var(--good)}' +
  '.pd-ban{border-radius:8px;padding:10px 12px;margin-bottom:10px;border:1px solid}.pd-ban.bad{background:var(--badbg);border-color:var(--bad);color:var(--tx)}.pd-ban.warn{background:var(--warnbg);border-color:var(--warn)}' +
  '.pd-ban b{color:var(--bad)}.pd-ban.warn b{color:var(--warn)}.pd details{margin-top:6px}.pd summary{cursor:pointer;color:var(--mu)}' +
  '.pd-tw{overflow:auto;border:1px solid var(--bd);border-radius:8px;background:var(--card)}.pd table{border-collapse:collapse;width:100%;font-size:13px}' +
  '.pd th{position:sticky;top:0;background:var(--ac2);text-align:left;padding:6px 8px;white-space:nowrap;font-weight:600;border-bottom:1px solid var(--bd);cursor:pointer;user-select:none}' +
  '.pd td{padding:5px 8px;border-bottom:1px solid var(--bd);vertical-align:top}.pd td.r,.pd th.r{text-align:right;font-variant-numeric:tabular-nums}.pd tr:hover td{background:var(--ac2)}' +
  '.pd tr.rowc{cursor:pointer}.pd td.neg{color:var(--bad)}.pd tr.b td{font-weight:700}.pd td.sticky,.pd th.sticky{position:sticky;left:0;background:var(--card)}.pd th.sticky{background:var(--ac2);z-index:2}' +
  '.pd-tools{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px;align-items:center}.pd input,.pd select{font:inherit;color:var(--tx);background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:5px 8px}' +
  '.pd button.pd-btn{font:inherit;border:1px solid var(--bd);background:var(--card);color:var(--tx);border-radius:6px;padding:5px 10px;cursor:pointer}.pd button.pd-btn:hover{background:var(--ac2)}' +
  '.pd-pg{display:flex;gap:8px;align-items:center;justify-content:flex-end;margin-top:6px;color:var(--mu);font-size:12px}' +
  '.pd-badge{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;font-weight:600;white-space:nowrap;background:var(--ac2);color:var(--ac)}' +
  '.pd-badge.REY{background:#d8f0dc;color:#1b5e20}.pd-badge.MEDIO{background:#dbe8fb;color:#1a3f7a}.pd-badge.REVENTAR{background:#fde0d6;color:#8a2a10}.pd-badge.COLA{background:#e7e9ee;color:#4a5568}.pd-badge.PREVENTA{background:#e8def7;color:#4b2a85}' +
  '.pd-badge.CRITICA{background:var(--bad);color:#fff}.pd-badge.ALTA{background:var(--warn);color:#fff}.pd-badge.MEDIA{background:var(--ac);color:#fff}.pd-badge.BAJA{background:#8a94a6;color:#fff}.pd-badge.RESERVADO{background:var(--warnbg);color:var(--warn);border:1px solid var(--warn)}' +
  '.pd-al{cursor:pointer}.pd-al:hover{border-color:var(--ac)}.pd-al .v{font-size:20px;font-weight:700}.pd-al .u{color:var(--mu);font-size:12px}' +
  '.pd svg text{fill:var(--mu);font-size:10px}.pd svg .ax{stroke:var(--bd)}.pd-leg{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--mu);margin-top:4px}.pd-leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}' +
  '.pd-bar{height:8px;border-radius:4px;background:var(--ac);min-width:1px}.pd-ul{margin:4px 0 0 18px;padding:0}.pd-ul li{margin:2px 0}' +
  '.pd-modal{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:9999;padding:16px}.pd-modal>div{max-width:620px;width:100%;max-height:90vh;overflow:auto}' +
  '.pd-kv{display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;font-size:13px}.pd-kv span:nth-child(odd){color:var(--mu)}.pd-foot{color:var(--mu);font-size:11px;margin-top:12px}';

  function injectCss() {
    if (document.getElementById('pd-style')) return;
    var s = document.createElement('style'); s.id = 'pd-style'; s.textContent = CSS; document.head.appendChild(s);
  }

  // ------------------------------------------------------------------ gráficos SVG
  function chartBar(o) {  // {labels, series:[{name,values,color,colors}], fmt, h}
    var W = 620, H = o.h || 230, ml = 54, mr = 8, mt = 10, mb = 26, n = o.labels.length, ns = o.series.length;
    var all = []; o.series.forEach(function (s) { s.values.forEach(function (v) { all.push(isNum(v) ? v : 0); }); });
    var mx = Math.max.apply(null, all.concat([0])), mn = Math.min.apply(null, all.concat([0]));
    if (mx === mn) mx = mn + 1;
    var y = function (v) { return mt + (H - mt - mb) * (1 - (v - mn) / (mx - mn)); };
    var g = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img' });
    for (var t = 0; t <= 4; t++) {
      var tv = mn + (mx - mn) * t / 4, ty = y(tv);
      g.appendChild(svg('line', { x1: ml, x2: W - mr, y1: ty, y2: ty, class: 'ax' }));
      var tx = svg('text', { x: ml - 4, y: ty + 3, 'text-anchor': 'end' }); tx.textContent = (o.fmt || fUsdC)(tv).replace('US$ ', ''); g.appendChild(tx);
    }
    var bw = (W - ml - mr) / n, gw = bw * 0.78, sw = gw / ns, z = y(0);
    o.labels.forEach(function (lb, i) {
      var x0 = ml + i * bw + (bw - gw) / 2;
      o.series.forEach(function (s, j) {
        var v = isNum(s.values[i]) ? s.values[i] : 0, yy = y(v), col = (s.colors && s.colors[i]) || s.color || '#2f5597';
        var r = svg('rect', { x: x0 + j * sw, y: Math.min(yy, z), width: Math.max(1, sw - 1), height: Math.max(0.5, Math.abs(z - yy)), fill: col, rx: 2 });
        var tt = svg('title'); tt.textContent = lb + (ns > 1 ? ' · ' + s.name : '') + ': ' + (o.fmt || fUsd)(v); r.appendChild(tt); g.appendChild(r);
      });
      if (n <= 16 || i % Math.ceil(n / 16) === 0) { var xl = svg('text', { x: ml + i * bw + bw / 2, y: H - 8, 'text-anchor': 'middle' }); xl.textContent = lb; g.appendChild(xl); }
    });
    var box = el('div'); box.appendChild(g);
    if (ns > 1) box.appendChild(el('div', { class: 'pd-leg' }, o.series.map(function (s) { var i = el('i'); i.style.background = s.color; return el('span', null, [i, s.name]); })));
    return box;
  }
  function chartLine(o) {
    var W = 620, H = o.h || 230, ml = 54, mr = 10, mt = 10, mb = 26, n = o.labels.length;
    var all = []; o.series.forEach(function (s) { s.values.forEach(function (v) { all.push(isNum(v) ? v : 0); }); });
    var mx = Math.max.apply(null, all.concat([0])), mn = Math.min.apply(null, all.concat([0]));
    if (mx === mn) mx = mn + 1;
    var y = function (v) { return mt + (H - mt - mb) * (1 - (v - mn) / (mx - mn)); };
    var x = function (i) { return ml + (W - ml - mr) * (n === 1 ? 0.5 : i / (n - 1)); };
    var g = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img' });
    for (var t = 0; t <= 4; t++) {
      var tv = mn + (mx - mn) * t / 4, ty = y(tv);
      g.appendChild(svg('line', { x1: ml, x2: W - mr, y1: ty, y2: ty, class: 'ax' }));
      var tx = svg('text', { x: ml - 4, y: ty + 3, 'text-anchor': 'end' }); tx.textContent = (o.fmt || fUsdC)(tv).replace('US$ ', ''); g.appendChild(tx);
    }
    o.series.forEach(function (s) {
      var pts = s.values.map(function (v, i) { return x(i) + ',' + y(isNum(v) ? v : 0); }).join(' ');
      g.appendChild(svg('polyline', { points: pts, fill: 'none', stroke: s.color, 'stroke-width': 2 }));
      s.values.forEach(function (v, i) {
        var c = svg('circle', { cx: x(i), cy: y(isNum(v) ? v : 0), r: 3, fill: s.color });
        var tt = svg('title'); tt.textContent = o.labels[i] + ' · ' + s.name + ': ' + (o.fmt || fUsd)(v); c.appendChild(tt); g.appendChild(c);
      });
    });
    o.labels.forEach(function (lb, i) { if (n <= 16 || i % Math.ceil(n / 16) === 0) { var xl = svg('text', { x: x(i), y: H - 8, 'text-anchor': 'middle' }); xl.textContent = lb; g.appendChild(xl); } });
    var box = el('div'); box.appendChild(g);
    if (o.series.length > 1) box.appendChild(el('div', { class: 'pd-leg' }, o.series.map(function (s) { var i = el('i'); i.style.background = s.color; return el('span', null, [i, s.name]); })));
    return box;
  }

  // ------------------------------------------------------------------ tabla genérica
  function table(o) {  // {cols:[{key,label,val,fmt,cls,num,html}], rows, pageSize, onRow, csv, sortKey, sortDir}
    var st = { page: 0, sk: o.sortKey || null, sd: o.sortDir || -1 }, ps = o.pageSize || 0;
    var wrap = el('div'), tw = el('div', { class: 'pd-tw' }), pg = el('div', { class: 'pd-pg' });
    var tools = el('div', { class: 'pd-tools' });
    if (o.csv) tools.appendChild(el('button', { class: 'pd-btn', type: 'button', text: 'Descargar CSV', onclick: function () { downloadCsv(o.csv, o.cols, sorted()); } }));
    function sorted() {
      var rows = o.rows.slice();
      if (st.sk != null) { var c = o.cols[st.sk]; rows.sort(function (a, b) {
        var x = c.val(a), y = c.val(b); var xn = x == null || x === '', yn = y == null || y === '';
        if (xn && yn) return 0; if (xn) return 1; if (yn) return -1;
        if (typeof x === 'number' && typeof y === 'number') return (x - y) * st.sd;
        return String(x).localeCompare(String(y), 'es') * st.sd; }); }
      return rows;
    }
    function draw() {
      tw.innerHTML = ''; pg.innerHTML = '';
      var rows = sorted(), tot = rows.length, pages = ps ? Math.max(1, Math.ceil(tot / ps)) : 1;
      if (st.page >= pages) st.page = pages - 1;
      var view = ps ? rows.slice(st.page * ps, st.page * ps + ps) : rows;
      var thead = el('tr'); o.cols.forEach(function (c, i) {
        var th = el('th', { class: (c.num ? 'r ' : '') + (c.sticky ? 'sticky' : ''), title: 'Ordenar' }, c.label + (st.sk === i ? (st.sd < 0 ? ' ▼' : ' ▲') : ''));
        th.addEventListener('click', function () { if (st.sk === i) st.sd = -st.sd; else { st.sk = i; st.sd = c.num ? -1 : 1; } draw(); });
        thead.appendChild(th);
      });
      var tb = el('tbody');
      view.forEach(function (r) {
        var tr = el('tr', { class: (o.onRow ? 'rowc ' : '') + (o.rowCls ? o.rowCls(r) : '') });
        if (o.onRow) tr.addEventListener('click', function () { o.onRow(r); });
        o.cols.forEach(function (c) {
          var v = c.val(r), td = el('td', { class: (c.num ? 'r ' : '') + (c.sticky ? 'sticky ' : '') + (c.neg && isNum(v) && v < 0 ? 'neg' : '') });
          var shown = c.fmt ? c.fmt(v, r) : (v == null ? '' : v);
          if (c.node) { var nd = c.node(v, r); if (nd) td.appendChild(nd); } else td.textContent = shown == null ? '' : shown;
          tr.appendChild(td);
        });
        tb.appendChild(tr);
      });
      if (!view.length) tb.appendChild(el('tr', null, el('td', { colspan: o.cols.length, text: 'Sin resultados' })));
      tw.appendChild(el('table', null, [el('thead', null, thead), tb]));
      if (ps && tot > ps) {
        pg.appendChild(el('span', { text: (st.page * ps + 1) + '–' + Math.min(tot, st.page * ps + ps) + ' de ' + fInt(tot) }));
        pg.appendChild(el('button', { class: 'pd-btn', type: 'button', text: '‹', onclick: function () { if (st.page > 0) { st.page--; draw(); } } }));
        pg.appendChild(el('button', { class: 'pd-btn', type: 'button', text: '›', onclick: function () { if (st.page < pages - 1) { st.page++; draw(); } } }));
      } else pg.appendChild(el('span', { text: fInt(tot) + ' filas' }));
    }
    draw(); wrap.appendChild(tools); wrap.appendChild(tw); wrap.appendChild(pg);
    wrap.update = function (rows) { o.rows = rows; st.page = 0; draw(); };
    return wrap;
  }
  function badge(txt) { return txt ? el('span', { class: 'pd-badge ' + String(txt).replace(/[^A-Za-zÁÉÍÓÚáéíóú]/g, '').replace('CRÍTICA', 'CRITICA'), text: txt }) : null; }
  function kpi(label, value, note, cls) { return el('div', { class: 'pd-card pd-kpi ' + (cls || '') }, [el('div', { class: 'v', text: value }), el('div', { class: 'l', text: label }), note ? el('div', { class: 'n', text: note }) : null]); }
  function card(title, body) { return el('div', { class: 'pd-card' }, [title ? el('h2', { text: title }) : null, body]); }

  // ------------------------------------------------------------------ componente principal
  function mount(root, data, opts) {
    opts = opts || {}; injectCss();
    root.innerHTML = ''; var app = el('div', { class: 'pd', 'data-theme': opts.theme || 'auto' }); root.appendChild(app);
    var D = data, K = D.kpis || {}, CAP = D.capital || { meses: [], series: {}, kpis: {} }, S = CAP.series || {};
    var TR = D.transito || { requerimientos: [], pagos: [], unidades_por_mes: [], resumen: {}, meses: [] };
    var cols = D.skus.cols, SK = D.skus.rows.map(function (r) { var o = {}; cols.forEach(function (c, i) { o[c] = r[i]; }); return o; });
    var state = { trFiltro: '', tab: 'resumen', f: { q: '', clase: '', pm: '', alerta: '', categoria: '', canal: '', sinCosto: false, alertaCosto: '' }, mesCompra: 'todos' };
    var TABS = [['resumen', 'Resumen'], ['compras', 'Compras'], ['transito', 'En camino'], ['capital', 'Capital'], ['skus', 'SKU'], ['alertas', 'Alertas'], ['margenes', 'Márgenes y canales'], ['datos', 'Datos y pendientes']];
    var content = el('div');
    var tabBar = el('div', { class: 'pd-tabs', role: 'tablist' });
    function go(tab) { state.tab = tab; render(); if (opts.onNavigate) opts.onNavigate(tab); }
    TABS.forEach(function (t) { tabBar.appendChild(el('button', { class: 'pd-tab', role: 'tab', 'data-tab': t[0], text: t[1], onclick: function () { go(t[0]); } })); });
    app.appendChild(el('div', { class: 'pd-head' }, [el('div', null, [el('h1', { text: opts.title || 'Proyección de compras e inversión 2027' }),
      el('div', { class: 'pd-sub', text: 'Escenario ' + (D.meta.escenario || '') + ' · ventas hasta ' + fMes(D.meta.corte_ventas) + ' · stock al ' + D.meta.corte_stock + ' · cifras en USD' })]),
      el('div', { class: 'pd-sub', text: 'Generado ' + D.meta.generado + ' · solo lectura' })]));
    app.appendChild(tabBar); app.appendChild(content);
    app.appendChild(el('div', { class: 'pd-foot', text: 'Fuente: ' + D.meta.fuente + ' · contrato de datos v' + D.meta.schema_version + ' · componente v' + VERSION }));

    function warns() {
      var w = D.meta.advertencias || []; if (!w.length) return null;
      var b = el('div', { class: 'pd-ban bad' }, [el('b', { text: 'Datos incompletos: ' }), w[0]]);
      if (w.length > 1) b.appendChild(el('details', null, [el('summary', { text: 'Otros límites y supuestos (' + (w.length - 1) + ')' }), el('ul', { class: 'pd-ul' }, w.slice(1).map(function (t) { return el('li', { text: t }); }))]));
      return b;
    }
    function alertaConteo(prefix) { var a = find((D.alertas && D.alertas.conteos) || [], function (c) { return c.alerta.indexOf(prefix) === 0; }); return a || { skus: null, stock_usd: null }; }

    // ---------- RESUMEN
    function renderResumen() {
      var f = el('div'); var b = warns(); if (b) f.appendChild(b);
      var rq = alertaConteo('Reyes SIN STOCK'), rq3 = alertaConteo('Reyes que se quedan'), mq = alertaConteo('Medios SIN STOCK'), mq3 = alertaConteo('Medios que se quedan');
      var g = el('div', { class: 'pd-grid pd-kpis' }, [
        kpi('Reyes', fInt(K.reyes), 'explican ' + fPct(K.pct_margen_reyes) + ' del margen', 'good'),
        kpi('Medios', fInt(K.medios), null),
        kpi('A reventar (capital parado)', fInt(K.reventar), fUsdC((find(D.clases, function (c) { return c.clase === 'REVENTAR'; }) || {}).stock_usd) + ' en stock', 'warn'),
        kpi('Stock total a costo real', fUsdC(K.stock_usd), fPct(K.pct_stock_reventar) + ' está en Reventar'),
        kpi('Reyes y Medios sin stock o con < 3 meses (descontando el tránsito)', fInt(K.rm_quiebre), fInt(rq.skus) + ' Reyes y ' + fInt(mq.skus) + ' Medios sin stock y sin nada en camino', 'bad'),
        kpi('Margen anualizado', fUsdC(K.margen_anual), 'últimos 6 meses de ventas reales'),
        kpi('Compras a emitir hasta ago-27', fUsdC(K.compras_usd), 'costo nacionalizado'),
        kpi('Compra de hoy (octubre)', fUsdC((S.compras_usd || [])[0]), 'llega en enero 2027'),
        kpi('Capital para 3 meses (máximo)', fUsdC(K.capital_3m_max), 'necesario en ' + fMes(K.capital_3m_mes), 'warn'),
        kpi('Facturación 2027 proyectada', fUsdC(K.fact_2027), 'sin IVA'),
        kpi('Caja liberable liquidando Reventar', fUsdC(K.caja_reventar), 'cubre ' + fPct((D.plata_liberada || {}).cobertura) + ' de las compras', 'good'),
        kpi('Mercadería en camino (FOB, pedidos con saldo)', fUsdC(K.fob_en_camino), 'saldo a pagar a proveedores: ' + fUsdC(sum(TR.pagos.map(function (p) { return p.saldo; })))),
        kpi('Pagos ya comprometidos (proveedores + aduana)', fUsdC(K.pagos_comprometidos), 'de pedidos ya emitidos, además de las compras nuevas', 'bad'),
        kpi('SKU activos', fInt(K.sku_activos), fInt(K.preventa) + ' son preventas (contra pedido)')]);
      f.appendChild(g);
      var n12 = (CAP.meses || []).slice(0, 12).map(fMes);
      f.appendChild(el('div', { class: 'pd-grid pd-2', style: 'margin-top:10px' }, [
        card('Compras a emitir por mes (USD, costo nacionalizado)', chartBar({ labels: n12, series: [{ name: 'Compras', values: (S.compras_usd || []).slice(0, 12), color: '#2f5597' }] })),
        card('Desembolsos vs. cobros por mes (USD)', chartLine({ labels: (CAP.meses || []).map(fMes), series: [{ name: 'Desembolsos', values: S.desembolso || [], color: '#c62828' }, { name: 'Cobros netos', values: S.cobros || [], color: '#2e7d32' }] })),
        card('Stock a costo real por clase (USD)', chartBar({ labels: D.clases.filter(function (c) { return c.clase !== 'TOTAL'; }).map(function (c) { return c.clase; }), series: [{ name: 'Stock', values: D.clases.filter(function (c) { return c.clase !== 'TOTAL'; }).map(function (c) { return c.stock_usd; }), color: '#b26a00' }] })),
        card('Margen anualizado por clase (USD)', chartBar({ labels: D.clases.filter(function (c) { return c.clase !== 'TOTAL'; }).map(function (c) { return c.clase; }), series: [{ name: 'Margen', values: D.clases.filter(function (c) { return c.clase !== 'TOTAL'; }).map(function (c) { return c.margen_usd; }), color: '#2e7d32' }] }))]));
      var lst = el('ul', { class: 'pd-ul' }, [
        el('li', { text: 'Reyes sin stock hoy y sin nada en camino: ' + fInt(rq.skus) + ' (más ' + fInt(alertaConteo('Reyes sin stock hoy').skus) + ' sin stock pero con pedido en camino); se quedan sin stock en menos de 3 meses: ' + fInt(rq3.skus) + '.' }),
        el('li', { text: 'Capital parado: ' + fUsdC(alertaConteo('REVENTAR').stock_usd) + ' en ' + fInt(alertaConteo('REVENTAR').skus) + ' SKU para liquidar; más ' + fUsdC(alertaConteo('Reyes con STOCK PARADO').stock_usd + alertaConteo('Medios con STOCK PARADO').stock_usd) + ' en Reyes y Medios con exceso.' }),
        el('li', { text: 'Plata: ya hay ' + fUsdC(K.pagos_comprometidos) + ' comprometidos con proveedores y aduana por pedidos en camino. El mayor desembolso mensual es ' + fUsdC((CAP.kpis || {})['Mayor desembolso mensual (USD)']) + ' en ' + fMes((CAP.kpis || {})['Mes del mayor desembolso']) + ' y hay que tener ' + fUsdC(K.capital_3m_max) + ' para los 3 meses desde ' + fMes(K.capital_3m_mes) + '.' }),
        el('li', { text: 'Validar con Marcelo y Leandro los pedidos del cruce (pestaña En camino): el 6851 de SkyFord no está en el Excel de Marcelo y suma 250 mil unidades.' })]);
      f.appendChild(el('div', { style: 'margin-top:10px' }, card('Qué mirar primero', lst)));
      return f;
    }

    // ---------- COMPRAS
    function renderCompras() {
      var f = el('div'), b = warns(); if (b) f.appendChild(b);
      var meses = (CAP.meses || []).slice(0, 12), sel = state.mesCompra;
      var tools = el('div', { class: 'pd-tools' }), s = el('select');
      s.appendChild(el('option', { value: 'todos', text: 'Todos los meses (hasta ago-27)' }));
      meses.forEach(function (m, i) { s.appendChild(el('option', { value: String(i), text: 'Emitir en ' + fMes(m) + ' (llega ' + fMes(CAP.meses[i + 3] || '') + ')' })); });
      s.value = sel; s.addEventListener('change', function () { state.mesCompra = s.value; render(); });
      tools.appendChild(el('span', { text: 'Ver compras de: ' })); tools.appendChild(s); f.appendChild(tools);
      var idx = sel === 'todos' ? null : parseInt(sel, 10);
      var rows = D.compras_sku.map(function (c) {
        var u = idx == null ? c.unid_total : c.unid[idx]; return { c: c, u: u, usd: (u || 0) * (c.costo || 0) };
      }).filter(function (r) { return r.u > 0; });
      var totU = sum(rows.map(function (r) { return r.u; })), totUsd = sum(rows.map(function (r) { return r.usd; }));
      var byClase = {}; rows.forEach(function (r) { byClase[r.c.clase] = (byClase[r.c.clase] || 0) + r.usd; });
      f.appendChild(el('div', { class: 'pd-grid pd-kpis' }, [kpi('Total a comprar', fUsdC(totUsd), idx == null ? 'hasta ago-27' : fMes(meses[idx])), kpi('Unidades', fInt(totU), null), kpi('SKU a pedir', fInt(rows.length), null)]
        .concat(Object.keys(byClase).map(function (k) { return kpi('Clase ' + k, fUsdC(byClase[k]), fPct(totUsd ? byClase[k] / totUsd : 0) + ' del total'); }))));
      f.appendChild(el('div', { style: 'margin:10px 0' }, card('Compras emitidas por mes (USD)', chartBar({ labels: meses.map(fMes), series: [{ name: 'Compras', values: (S.compras_usd || []).slice(0, 12), colors: meses.map(function (m, i) { return idx === i ? '#c62828' : '#2f5597'; }), color: '#2f5597' }] }))));
      f.appendChild(table({ csv: 'compras_' + (idx == null ? 'total' : meses[idx]), sortKey: 4, pageSize: 40, cols: [
        { label: 'SKU', val: function (r) { return r.c.sku; }, sticky: true }, { label: 'Clase', val: function (r) { return r.c.clase; }, node: function (v) { return badge(v); } },
        { label: 'PM', val: function (r) { return r.c.pm; } }, { label: 'Categoría', val: function (r) { return r.c.categoria; } },
        { label: 'USD', val: function (r) { return r.usd; }, fmt: fUsd, num: true }, { label: 'Unidades a pedir', val: function (r) { return r.u; }, fmt: fInt, num: true },
        { label: 'Costo unit. USD', val: function (r) { return r.c.costo; }, fmt: f2, num: true }, { label: 'Stock hoy', val: function (r) { return r.c.stock; }, fmt: fInt, num: true },
        { label: 'Venta mensual (prom 6m)', val: function (r) { return r.c.prom6m; }, fmt: fInt, num: true }], rows: rows,
        onRow: function (r) { showSku(r.c.sku); } }));
      f.appendChild(el('div', { class: 'pd-foot', text: 'Cada pedido llega 3 meses después de emitido. No descuenta mercadería en tránsito ni pedidos abiertos (pendiente P01). Preventas, Reventar y Cola no se recompran.' }));
      return f;
    }

    // ---------- EN CAMINO
    var CLASE_TXT = { FIRME: 'Firme (cuenta)', FIRME_SIN_ESTADO: 'Firme sin estado (cuenta)', NO_ESTA_EN_MARCELO: 'No está en Marcelo (no cuenta)', NO_FIRME: 'Cotizando / coordinar (no cuenta)', SIN_ESTADO_SIN_FOB: 'Sin estado ni FOB (no cuenta)' };
    function renderTransito() {
      var f = el('div'), b = warns(); if (b) f.appendChild(b);
      var rs = TR.resumen || {}, firmes = TR.requerimientos.filter(function (c) { return c.clasificacion === 'FIRME' || c.clasificacion === 'FIRME_SIN_ESTADO'; });
      var fu = sum(firmes.map(function (c) { return c.unidades; })), ff = sum(firmes.map(function (c) { return c.fob; })), fs = sum(firmes.map(function (c) { return c.saldo; }));
      var nm = rs.NO_ESTA_EN_MARCELO || { requerimientos: 0, unidades: 0 };
      var sinFecha = firmes.filter(function (c) { return (c.fuente_fecha || '').indexOf('SIN FECHA') === 0; }).length;
      var corte = D.meta.corte_transito || D.meta.generado;
      var vencidas = firmes.filter(function (c) { return c.eta_marcelo && c.eta_marcelo < corte; }).length;
      f.appendChild(el('div', { class: 'pd-grid pd-kpis' }, [
        kpi('Pedidos firmes en camino', fInt(firmes.length) + ' requerimientos', fInt(fu) + ' unidades · FOB ' + fUsdC(ff)),
        kpi('Saldo a pagar a proveedores', fUsdC(fs), 'de esos pedidos'),
        kpi('Pagos comprometidos con aduana', fUsdC(K.pagos_comprometidos), 'saldos + gravámenes y gastos', 'bad'),
        kpi('Abiertos en Táctica que Marcelo no tiene', fInt(nm.requerimientos), fInt(nm.unidades) + ' unidades: no se cuentan hasta validarlos', 'warn'),
        kpi('Pedidos sin fecha de entrega', fInt(sinFecha), 'se suponen a ' + ((TR.supuestos || {}).sin_fecha_dias_desde_hoy || 90) + ' días', 'warn'),
        kpi('ETA vencida y abierto en Táctica', fInt(vencidas), '¿ya llegaron y falta ingresarlos?', 'warn')]));
      var ms = (TR.meses || []).map(fMes);
      f.appendChild(el('div', { class: 'pd-grid pd-2', style: 'margin:10px 0' }, [
        card('Unidades que entran al stock por mes (pedidos firmes)', chartBar({ labels: ms, fmt: fInt, series: [{ name: 'Unidades', values: TR.unidades_por_mes || [], color: '#2e7d32' }] })),
        card('Pagos ya comprometidos por mes (USD)', chartBar({ labels: (CAP.meses || []).map(fMes), series: [{ name: 'Saldos a proveedores', values: S.saldos_en_camino || [], color: '#2f5597' }, { name: 'Gravámenes y gastos', values: S.gravamenes_en_camino || [], color: '#b26a00' }] }))]));
      var tools = el('div', { class: 'pd-tools' }), sl = el('select'); sl.appendChild(el('option', { value: '', text: 'Todas las clasificaciones' }));
      Object.keys(CLASE_TXT).forEach(function (k) { sl.appendChild(el('option', { value: k, text: CLASE_TXT[k] })); });
      sl.value = state.trFiltro; sl.addEventListener('change', function () { state.trFiltro = sl.value; render(); });
      tools.appendChild(el('span', { text: 'Requerimientos abiertos en Táctica: ' })); tools.appendChild(sl); f.appendChild(tools);
      var rows = TR.requerimientos.filter(function (c) { return !state.trFiltro || c.clasificacion === state.trFiltro; });
      f.appendChild(table({ csv: 'cruce_transito', sortKey: 4, pageSize: 25, cols: [
        { label: 'REQ', val: function (c) { return c.req; }, sticky: true }, { label: 'Proveedor', val: function (c) { return c.proveedor; } }, { label: 'Clasificación', val: function (c) { return CLASE_TXT[c.clasificacion] || c.clasificacion; } },
        { label: 'Estado (Marcelo)', val: function (c) { return c.estado_marcelo; } }, { label: 'Unidades', val: function (c) { return c.unidades; }, fmt: fInt, num: true }, { label: 'FOB USD', val: function (c) { return c.fob; }, fmt: fInt, num: true },
        { label: 'Saldo USD', val: function (c) { return c.saldo; }, fmt: fInt, num: true }, { label: 'Días abierto', val: function (c) { return c.dias_abierto; }, fmt: fInt, num: true }, { label: 'ETA (Marcelo)', val: function (c) { return c.eta_marcelo; } },
        { label: 'ETA usada', val: function (c) { return c.eta_usada; } }, { label: 'Fuente de la fecha', val: function (c) { return c.fuente_fecha; } }, { label: 'Qué resolver', val: function (c) { return c.resolver; } }], rows: rows }));
      var skuRows = SK.filter(function (r) { return (r.transito || 0) > 0; });
      f.appendChild(el('h2', { style: 'margin:16px 0 6px', text: 'SKU con mercadería en camino (' + fInt(skuRows.length) + ')' }));
      f.appendChild(table({ csv: 'skus_en_camino', sortKey: 5, pageSize: 20, cols: [
        { label: 'SKU', val: function (r) { return r.sku; }, sticky: true }, { label: 'PM', val: function (r) { return r.pm; } }, { label: 'Categoría', val: function (r) { return r.categoria; } },
        { label: 'Clase', val: function (r) { return r.clase; }, node: function (v) { return badge(v); } }, { label: 'Stock hoy', val: function (r) { return r.stock; }, fmt: fInt, num: true },
        { label: 'En tránsito', val: function (r) { return r.transito; }, fmt: fInt, num: true }, { label: 'Venta mensual (prom 6m)', val: function (r) { return r.prom6m; }, fmt: fInt, num: true },
        { label: 'Primera llegada', val: function (r) { return r.primera_llegada; }, fmt: function (v) { return v ? fMes(v) : ''; } }], rows: skuRows, onRow: function (r) { showSku(r.sku); } }));
      f.appendChild(el('div', { class: 'pd-foot', text: 'Un pedido cuenta como mercadería en camino solo si está abierto en Táctica y figura firme en el Excel de Marcelo (embarcado, sin fecha de entrega o arribado). Se suman ' + ((TR.supuestos || {}).demora_eta_disponible_dias || 30) + ' días entre la ETA y poder vender. Hay SKU nuevos en camino sin historial de ventas que no entran a la proyección.' }));
      return f;
    }

    // ---------- CAPITAL
    function renderCapital() {
      var f = el('div'), b = warns(); if (b) f.appendChild(b);
      var ck = CAP.kpis || {};
      f.appendChild(el('div', { class: 'pd-grid pd-kpis' }, [
        kpi('Capital máximo para 3 meses', fUsdC(ck['Capital máximo a tener para 3 meses (USD)']), 'necesario en ' + fMes(ck['Mes en que se necesita']), 'warn'),
        kpi('Mayor desembolso mensual', fUsdC(ck['Mayor desembolso mensual (USD)']), fMes(ck['Mes del mayor desembolso'])),
        kpi('Facturación mínima a cobrar antes', fUsdC(ck['Facturación mínima a cobrar antes de ese mes (USD)']), 'para cubrir esos 3 meses'),
        kpi('Compras hasta ago-27', fUsdC(ck['Compras emitidas hasta ago-27 (USD, costo nacionalizado)']), 'costo nacionalizado'),
        kpi('Caja acumulada mínima', fUsdC(ck['Caja acumulada mínima (USD)']), fMes(ck['Mes de caja mínima']) + ' · sin caja inicial ni gastos', ck['Caja acumulada mínima (USD)'] < 0 ? 'bad' : ''),
        kpi('Facturación 2027 proyectada', fUsdC(ck['Facturación 2027 proyectada (USD, ene-dic)']), 'sin IVA')]));
      var ms = (CAP.meses || []).map(fMes);
      f.appendChild(el('div', { class: 'pd-grid pd-2', style: 'margin:10px 0' }, [
        card('Capital a tener para los próximos 3 meses (USD)', chartBar({ labels: ms, series: [{ name: 'Capital 3m', values: S.capital_3m || [], color: '#b26a00' }] })),
        card('Caja acumulada (USD)', chartLine({ labels: ms, series: [{ name: 'Caja acumulada', values: S.caja_acum || [], color: '#2f5597' }] })),
        card('Valor del stock proyectado a fin de mes (USD, a costo)', chartLine({ labels: ms, series: [{ name: 'Stock total', values: S.stock_usd || [], color: '#2f5597' }, { name: 'Reventar', values: S.stock_reventar_usd || [], color: '#b26a00' }] })),
        card('Desembolsos por concepto (USD)', chartBar({ labels: ms, series: [{ name: 'Anticipo', values: S.anticipo || [], color: '#2f5597' }, { name: 'Saldo FOB', values: S.saldo || [], color: '#7fa4ee' }, { name: 'Nacionalización', values: S.nacionalizacion || [], color: '#b26a00' }, { name: 'Saldos pedidos en camino', values: S.saldos_en_camino || [], color: '#c62828' }, { name: 'Aduana pedidos en camino', values: S.gravamenes_en_camino || [], color: '#8a2a10' }] }))]));
      var rowsDef = [['compras_usd', 'Compras emitidas (costo nacionalizado)'], ['anticipo', 'Pago de anticipo a proveedor'], ['saldo', 'Pago de saldo FOB (al llegar)'], ['nacionalizacion', 'Nacionalización (al llegar)'], ['saldos_en_camino', 'Saldos a proveedores de pedidos en camino'], ['gravamenes_en_camino', 'Gravámenes y gastos de pedidos en camino'],
        ['otros_embarque', 'Otros costos de embarque (RESERVADO)'], ['desembolso', 'TOTAL DESEMBOLSOS', 1], ['capital_3m', 'CAPITAL PRÓXIMOS 3 MESES', 1], ['facturacion', 'Facturación proyectada sin IVA'], ['cobros', 'Cobros netos'],
        ['liquidacion_reventar', 'Caja por liquidar Reventar'], ['opex', 'Gastos operativos (RESERVADO)'], ['flujo', 'FLUJO NETO', 1], ['caja_acum', 'CAJA ACUMULADA', 1], ['stock_usd', 'Valor del stock proyectado'], ['stock_reventar_usd', '  de los cuales Reventar'],
        ['tc', 'Tipo de cambio (ARS/USD)'], ['desembolso_ars', 'Total desembolsos en ARS']];
      var head = el('tr', null, [el('th', { class: 'sticky', text: 'USD' })].concat(ms.map(function (m) { return el('th', { class: 'r', text: m }); })));
      var body = el('tbody', null, rowsDef.map(function (rd) {
        var vals = S[rd[0]] || []; return el('tr', { class: rd[2] ? 'b' : '' }, [el('td', { class: 'sticky', text: rd[1] })].concat(vals.map(function (v) { return el('td', { class: 'r' + (isNum(v) && v < 0 ? ' neg' : ''), text: rd[0] === 'tc' ? f2(v) : fInt(v) }); })));
      }));
      f.appendChild(el('div', { class: 'pd-tw' }, el('table', null, [el('thead', null, head), body])));
      f.appendChild(el('div', { class: 'pd-foot', text: 'Mes 0 = octubre 2026. Cada compra paga anticipo al emitirse y saldo + nacionalización al llegar (3 meses después). La curva ya incluye los saldos y la aduana de los pedidos en camino (hoja En camino), pero NO incluye caja inicial ni gastos operativos (pendiente P03).' }));
      return f;
    }

    // ---------- SKU
    function applyFilters() {
      var q = state.f.q.trim().toLowerCase();
      return SK.filter(function (r) {
        var f = state.f;
        if (f.clase && r.clase !== f.clase) return false; if (f.pm && r.pm !== f.pm) return false; if (f.categoria && r.categoria !== f.categoria) return false;
        if (f.canal && r.canal !== f.canal) return false;
        if (f.alerta && (r.alerta || '') !== f.alerta) return false;
        if (f.sinCosto && !((r.stock || 0) > 0 && r.costo == null)) return false;
        if (f.alertaCosto && (r.alerta_costo || '').indexOf(f.alertaCosto) !== 0) return false;
        if (q && (r.sku + ' ' + (r.categoria || '') + ' ' + (r.pm || '')).toLowerCase().indexOf(q) < 0) return false;
        return true;
      });
    }
    function uniq(k) { var m = {}; SK.forEach(function (r) { if (r[k]) m[r[k]] = 1; }); return Object.keys(m).sort(function (a, b) { return a.localeCompare(b, 'es'); }); }
    var tblSku = null;
    function renderSkus() {
      var f = el('div'), b = warns(); if (b) f.appendChild(b);
      var tools = el('div', { class: 'pd-tools' });
      function sel(key, label, opts2) { var s = el('select'); s.appendChild(el('option', { value: '', text: label })); opts2.forEach(function (o) { s.appendChild(el('option', { value: o, text: o })); }); s.value = state.f[key]; s.addEventListener('change', function () { state.f[key] = s.value; refresh(); }); return s; }
      var q = el('input', { type: 'search', placeholder: 'Buscar SKU, categoría o PM…', value: state.f.q }); q.addEventListener('input', function () { state.f.q = q.value; refresh(); });
      tools.appendChild(q); tools.appendChild(sel('clase', 'Todas las clases', ['REY', 'MEDIO', 'REVENTAR', 'COLA', 'PREVENTA'])); tools.appendChild(sel('pm', 'Todos los PM', uniq('pm')));
      tools.appendChild(sel('alerta', 'Todas las alertas de stock', ['QUIEBRE', 'SIN STOCK (LLEGA TRÁNSITO)', 'QUIEBRE EN <3 MESES', 'STOCK PARADO', 'LIQUIDAR', 'CONTRA PEDIDO', 'OK'])); tools.appendChild(sel('categoria', 'Todas las categorías', uniq('categoria')));
      var chk = el('label', null, [el('input', { type: 'checkbox' }), ' stock sin costo']); chk.firstChild.checked = state.f.sinCosto; chk.firstChild.addEventListener('change', function () { state.f.sinCosto = chk.firstChild.checked; refresh(); }); tools.appendChild(chk);
      tools.appendChild(el('button', { class: 'pd-btn', type: 'button', text: 'Limpiar filtros', onclick: function () { state.f = { q: '', clase: '', pm: '', alerta: '', categoria: '', canal: '', sinCosto: false, alertaCosto: '' }; render(); } }));
      f.appendChild(tools);
      var info = el('div', { class: 'pd-sub', style: 'margin-bottom:6px' }); f.appendChild(info);
      tblSku = table({ csv: 'skus', sortKey: 10, pageSize: 40, cols: [
        { label: 'SKU', val: function (r) { return r.sku; }, sticky: true }, { label: 'PM', val: function (r) { return r.pm; } }, { label: 'Categoría', val: function (r) { return r.categoria; } },
        { label: 'Clase', val: function (r) { return r.clase; }, node: function (v) { return badge(v); } }, { label: 'Stock', val: function (r) { return r.stock; }, fmt: fInt, num: true, neg: true },
        { label: 'Unid 12m', val: function (r) { return r.unid12m; }, fmt: fInt, num: true }, { label: 'Prom 6m', val: function (r) { return r.prom6m; }, fmt: fInt, num: true },
        { label: 'Cobertura (meses)', val: function (r) { return r.cobertura; }, fmt: f1, num: true }, { label: 'Alerta', val: function (r) { return r.alerta; } },
        { label: 'Costo USD', val: function (r) { return r.costo; }, fmt: f2, num: true }, { label: 'Margen anual USD', val: function (r) { return r.margen_anual; }, fmt: fInt, num: true, neg: true },
        { label: 'Margen %', val: function (r) { return r.margen_pct; }, fmt: function (v) { return fPct(v); }, num: true, neg: true }, { label: 'Canal ppal.', val: function (r) { return r.canal; } },
        { label: 'Compra USD', val: function (r) { return r.compra_usd; }, fmt: fInt, num: true }, { label: 'En tránsito', val: function (r) { return r.transito; }, fmt: fInt, num: true }, { label: 'Llega', val: function (r) { return r.primera_llegada; }, fmt: function (v) { return v ? fMes(v) : ''; } }], rows: applyFilters(), onRow: function (r) { showSku(r.sku); } });
      f.appendChild(tblSku);
      function refresh() { var rows = applyFilters(); tblSku.update(rows); info.textContent = fInt(rows.length) + ' de ' + fInt(SK.length) + ' SKU'; }
      info.textContent = fInt(applyFilters().length) + ' de ' + fInt(SK.length) + ' SKU';
      return f;
    }
    function showSku(sku) {
      var r = find(SK, function (x) { return x.sku === sku; }); if (!r) return;
      var c = find(D.compras_sku, function (x) { return x.sku === sku; });
      var kv = [['PM', r.pm], ['Categoría', r.categoria], ['Clase', r.clase], ['Alerta de stock', r.alerta], ['Stock hoy (u)', fInt(r.stock)], ['Stock a costo real', fUsd(r.stock_usd)], ['Unidades 12m', fInt(r.unid12m)], ['Venta mensual (prom 6m)', fInt(r.prom6m)],
        ['Meses con venta (12m)', fInt(r.meses12)], ['Cobertura (meses)', f1(r.cobertura)], ['Costo unitario USD', f2(r.costo)], ['Margen anualizado', fUsd(r.margen_anual)], ['Venta anualizada', fUsd(r.venta_anual)], ['Margen %', fPct(r.margen_pct, 1)],
        ['Canal principal', r.canal], ['Nivel de demanda (u/mes)', f1(r.nivel)], ['Demanda proyectada 2027 (u)', fInt(r.proy2027)], ['En tránsito (u)', fInt(r.transito)], ['Primera llegada', r.primera_llegada ? fMes(r.primera_llegada) : '–'], ['Compra total (u)', fInt(r.compra_unid)], ['Compra total USD', fUsd(r.compra_usd)], ['Alerta de costo', r.alerta_costo || '–'], ['Var. costo 6m', isNum(r.var_costo) ? fPct(r.var_costo, 0) : '–']];
      var body = el('div', { class: 'pd-kv' }); kv.forEach(function (p) { body.appendChild(el('span', { text: p[0] })); body.appendChild(el('span', { text: p[1] == null ? '–' : String(p[1]) })); });
      var inner = el('div', { class: 'pd-card' }, [el('h2', { text: r.sku }), body]);
      if (c) { inner.appendChild(el('h3', { style: 'margin-top:12px', text: 'Unidades a pedir por mes de emisión' })); inner.appendChild(chartBar({ labels: (CAP.meses || []).slice(0, 12).map(fMes), series: [{ name: 'Unidades', values: c.unid, color: '#2f5597' }], fmt: fInt, h: 150 })); }
      inner.appendChild(el('button', { class: 'pd-btn', type: 'button', text: 'Cerrar', style: 'margin-top:10px', onclick: function () { m.remove(); } }));
      var m = el('div', { class: 'pd-modal', onclick: function (e) { if (e.target === m) m.remove(); } }, el('div', null, inner)); app.appendChild(m);
    }

    // ---------- ALERTAS
    var ALERT_FILTER = [['Reyes sin stock hoy', { clase: 'REY', alerta: 'SIN STOCK (LLEGA TRÁNSITO)' }], ['Medios sin stock hoy', { clase: 'MEDIO', alerta: 'SIN STOCK (LLEGA TRÁNSITO)' }], ['Reyes SIN STOCK', { clase: 'REY', alerta: 'QUIEBRE' }], ['Reyes que se quedan', { clase: 'REY', alerta: 'QUIEBRE EN <3 MESES' }], ['Medios SIN STOCK', { clase: 'MEDIO', alerta: 'QUIEBRE' }], ['Medios que se quedan', { clase: 'MEDIO', alerta: 'QUIEBRE EN <3 MESES' }],
      ['Reyes con STOCK PARADO', { clase: 'REY', alerta: 'STOCK PARADO' }], ['Medios con STOCK PARADO', { clase: 'MEDIO', alerta: 'STOCK PARADO' }], ['REVENTAR', { clase: 'REVENTAR' }], ['PREVENTA con stock', { clase: 'PREVENTA' }],
      ['SKU con stock y SIN costo', { sinCosto: true }], ['SKU cuyo costo promedio BAJÓ', { alertaCosto: 'COSTO BAJÓ' }], ['SKU cuyo costo promedio SUBIÓ', { alertaCosto: 'COSTO SUBIÓ' }]];
    function renderAlertas() {
      var f = el('div'), b = warns(); if (b) f.appendChild(b);
      var g = el('div', { class: 'pd-grid pd-kpis' });
      ((D.alertas && D.alertas.conteos) || []).forEach(function (c) {
        var fl = find(ALERT_FILTER, function (a) { return c.alerta.indexOf(a[0]) === 0; });
        g.appendChild(el('div', { class: 'pd-card pd-al', title: 'Ver los SKU', onclick: function () { if (!fl) return; state.f = { q: '', clase: '', pm: '', alerta: '', categoria: '', canal: '', sinCosto: false, alertaCosto: '' }; for (var k in fl[1]) state.f[k] = fl[1][k]; go('skus'); } },
          [el('div', { class: 'v', text: fInt(c.skus) + ' SKU' }), el('div', { text: c.alerta }), isNum(c.stock_usd) ? el('div', { class: 'u', text: fUsdC(c.stock_usd) + ' en stock a costo real' }) : null]));
      });
      f.appendChild(g);
      var L = (D.alertas && D.alertas.listas) || {};
      Object.keys(L).forEach(function (k) {
        var l = L[k]; if (!l || !l.cols) return;
        var cdef = l.cols.map(function (name, i) {
          var numeric = l.rows.length && isNum(l.rows[0][i]);
          return { label: name, val: function (r) { return r[i]; }, num: numeric, fmt: numeric ? fInt : null, sticky: i === 0, node: name === 'Clase' ? function (v) { return badge(v); } : null };
        });
        f.appendChild(el('div', { style: 'margin-top:14px' }, [el('h2', { text: k }), table({ cols: cdef, rows: l.rows, onRow: function (r) { showSku(r[0]); } })]));
      });
      f.appendChild(el('div', { class: 'pd-foot', text: 'Las listas son una foto con los parámetros por defecto. El costo "bajó/subió" es la variación del costo promedio del ERP, no el costo de reposición: es una señal, no una conclusión.' }));
      return f;
    }

    // ---------- MÁRGENES
    function renderMargenes() {
      var f = el('div');
      var rows = D.canales.slice(); if (D.tactica) rows.push({ canal: 'Táctica (facturas)', lineas: D.tactica.lineas, venta_usd: D.tactica.venta_usd, margen_usd: D.tactica.margen_usd, margen_pct: D.tactica.margen_pct });
      var big = rows.filter(function (r) { return r.venta_usd > 20000; });
      f.appendChild(el('div', { class: 'pd-grid pd-2' }, [card('Margen % por canal (sobre venta sin IVA)', chartBar({ labels: big.map(function (r) { return r.canal.replace('Mercadolibre', 'ML').replace('Woocommerce', 'Web'); }), series: [{ name: 'Margen %', values: big.map(function (r) { return r.margen_pct; }), color: '#2e7d32' }], fmt: function (v) { return fPct(v); } })),
        card('Venta por canal (USD, 23/04 al 13/10)', chartBar({ labels: big.map(function (r) { return r.canal.replace('Mercadolibre', 'ML').replace('Woocommerce', 'Web'); }), series: [{ name: 'Venta', values: big.map(function (r) { return r.venta_usd; }), color: '#2f5597' }] }))]));
      f.appendChild(el('h2', { style: 'margin:14px 0 6px', text: 'Estructura por canal (% de la venta sin IVA)' }));
      var pc = function (k) { return { label: k[1], val: function (r) { return r[k[0]]; }, fmt: function (v) { return v == null ? '–' : fPct(v, 1); }, num: true }; };
      f.appendChild(table({ cols: [{ label: 'Canal', val: function (r) { return r.canal; }, sticky: true }, { label: 'Líneas', val: function (r) { return r.lineas; }, fmt: fInt, num: true }, { label: 'Venta USD', val: function (r) { return r.venta_usd; }, fmt: fInt, num: true },
        { label: 'Margen USD', val: function (r) { return r.margen_usd; }, fmt: fInt, num: true, neg: true }, pc(['margen_pct', 'Margen %']), pc(['costo_producto', 'Costo producto']), pc(['comisiones', 'Comisiones']), pc(['envio', 'Envío']), pc(['imp_cheque', 'Imp. cheque']), pc(['iibb', 'IIBB']), pc(['costo_operacion', 'Costo operación']), pc(['neto', 'Neto'])], rows: rows, sortKey: 2 }));
      f.appendChild(el('h2', { style: 'margin:14px 0 6px', text: 'Categorías: dónde está el margen y el capital' }));
      f.appendChild(table({ csv: 'categorias', sortKey: 3, cols: [{ label: 'Categoría', val: function (r) { return r.categoria; }, sticky: true }, { label: 'SKU', val: function (r) { return r.skus; }, fmt: fInt, num: true }, { label: 'Stock USD', val: function (r) { return r.stock_usd; }, fmt: fInt, num: true },
        { label: 'Margen anual USD', val: function (r) { return r.margen_usd; }, fmt: fInt, num: true, neg: true }, { label: 'Venta anual USD', val: function (r) { return r.venta_usd; }, fmt: fInt, num: true }, { label: 'Margen %', val: function (r) { return r.margen_pct; }, fmt: function (v) { return fPct(v); }, num: true },
        { label: 'Retorno anual por USD de stock', val: function (r) { return r.retorno; }, fmt: f2, num: true }, { label: 'Compras hasta ago-27 USD', val: function (r) { return r.compras_usd; }, fmt: fInt, num: true }], rows: D.categorias }));
      f.appendChild(el('h2', { style: 'margin:14px 0 6px', text: 'Estacionalidad (1,00 = mes promedio)' }));
      var head = el('tr', null, [el('th', { class: 'sticky', text: 'Grupo' }), el('th', { class: 'r', text: 'SKU' })].concat(MES.map(function (m) { return el('th', { class: 'r', text: m }); })));
      var body = el('tbody', null, D.estacionalidad.map(function (e) {
        return el('tr', null, [el('td', { class: 'sticky', text: e.grupo }), el('td', { class: 'r', text: fInt(e.skus) })].concat(e.indices.map(function (v) {
          var td = el('td', { class: 'r', text: f2(v) }); var a = v >= 1 ? Math.min(0.75, (v - 1) / 1.2) : Math.min(0.75, (1 - v) / 0.7);
          td.style.background = v >= 1 ? 'rgba(220,80,60,' + a + ')' : 'rgba(50,110,200,' + a + ')'; return td; })));
      }));
      f.appendChild(el('div', { class: 'pd-tw' }, el('table', null, [el('thead', null, head), body])));
      f.appendChild(el('div', { class: 'pd-foot', text: 'Regla vigente aplicada a todos los ciclos: neto = venta sin IVA − comisiones − envío − impuesto al cheque − IIBB − costo por operación ($149,12); margen = neto − costo del producto. Ecom 23/04 al 13/10/2026; Táctica 23/04 al 22/09/2026.' }));
      return f;
    }

    // ---------- DATOS Y PENDIENTES
    function renderDatos() {
      var f = el('div'), b = warns(); if (b) f.appendChild(b);
      var P = D.pendientes || [];
      f.appendChild(el('h2', { text: 'Datos pendientes y a quién pedírselos (propuesta para cerrar)' }));
      var resp = {}; P.forEach(function (p) { (resp[p.responsable] = resp[p.responsable] || []).push(p); });
      var chips = el('div', { class: 'pd-tools' });
      Object.keys(resp).forEach(function (k) {
        chips.appendChild(el('button', { class: 'pd-btn', type: 'button', text: 'Copiar pedido para ' + k.split(' (')[0].split(' +')[0], title: k, onclick: function () {
          var txt = 'Hola! Para cerrar la proyección de compras 2027 necesito:\n\n' + resp[k].map(function (p, i) { return (i + 1) + '. ' + p.dato + '\n   Detalle: ' + p.detalle + '\n   Formato: ' + p.formato; }).join('\n\n') + '\n\nGracias!';
          if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt); } }));
      });
      f.appendChild(chips);
      f.appendChild(table({ csv: 'pendientes', cols: [{ label: 'ID', val: function (p) { return p.id; } }, { label: 'Prioridad', val: function (p) { return p.prioridad; }, node: function (v) { return badge(v); } }, { label: 'Estado', val: function (p) { return p.estado || 'pendiente'; } }, { label: 'Dato que falta', val: function (p) { return p.dato; } },
        { label: 'Responsable sugerido', val: function (p) { return p.responsable; } }, { label: 'Detalle', val: function (p) { return p.detalle; } }, { label: 'Formato', val: function (p) { return p.formato; } }, { label: 'Por qué importa', val: function (p) { return p.impacto; } },
        { label: 'Dónde se carga', val: function (p) { return p.donde_se_carga; } }], rows: P }));
      f.appendChild(el('h2', { style: 'margin:16px 0 6px', text: 'Parámetros y supuestos' }));
      f.appendChild(table({ cols: [{ label: 'Parámetro', val: function (p) { return p.parametro; }, sticky: true }, { label: 'Valor', val: function (p) { return p.valor; }, fmt: function (v) { return isNum(v) ? (Math.abs(v) < 5 && v % 1 !== 0 ? v.toString().replace('.', ',') : fInt(v)) : v; }, num: true },
        { label: 'Tipo', val: function (p) { return p.tipo; }, node: function (v) { return badge(v); } }, { label: 'Qué es', val: function (p) { return p.detalle; } }], rows: D.parametros }));
      f.appendChild(el('h2', { style: 'margin:16px 0 6px', text: 'Calidad de la demanda: unidades por mes y de dónde sale cada dato' }));
      var dh = D.demanda_historica;
      f.appendChild(card(null, chartBar({ labels: dh.map(function (r) { return fMes(r.mes); }), h: 200, fmt: fInt, series: [{ name: 'Unidades', values: dh.map(function (r) { return r.total; }), color: '#2f5597',
        colors: dh.map(function (r) { var t = (r.estado_tactica || '') + ' ' + (r.estado_it || ''); return t.indexOf('ESTIMADO') >= 0 ? '#e0a800' : (t.indexOf('RECONSTRUIDO') >= 0 || t.indexOf('REPARADO') >= 0) ? '#e8743b' : '#2f5597'; }) }] })));
      f.appendChild(el('div', { class: 'pd-leg' }, [el('span', null, [(function () { var i = el('i'); i.style.background = '#2f5597'; return i; })(), 'dato de origen']), el('span', null, [(function () { var i = el('i'); i.style.background = '#e8743b'; return i; })(), 'reparado o reconstruido']), el('span', null, [(function () { var i = el('i'); i.style.background = '#e0a800'; return i; })(), 'estimado'])]));
      f.appendChild(el('div', { style: 'margin-top:8px' }, table({ pageSize: 15, sortKey: 0, sortDir: 1, cols: [{ label: 'Mes', val: function (r) { return r.mes; }, fmt: fMes }, { label: 'Fuente Ecom (IT)', val: function (r) { return r.estado_it; } }, { label: 'IT usado', val: function (r) { return r.it_usado; }, fmt: fInt, num: true },
        { label: 'Fuente Táctica', val: function (r) { return r.estado_tactica; } }, { label: 'Táctica usado', val: function (r) { return r.tactica_usado; }, fmt: fInt, num: true }, { label: 'Total', val: function (r) { return r.total; }, fmt: fInt, num: true }, { label: 'TC BNA', val: function (r) { return r.tc; }, fmt: f2, num: true }, { label: 'Nota', val: function (r) { return r.nota; } }], rows: dh })));
      return f;
    }

    function render() {
      Array.prototype.forEach.call(tabBar.children, function (b) { b.setAttribute('aria-selected', b.getAttribute('data-tab') === state.tab ? 'true' : 'false'); });
      content.innerHTML = '';
      var fn = { resumen: renderResumen, compras: renderCompras, transito: renderTransito, capital: renderCapital, skus: renderSkus, alertas: renderAlertas, margenes: renderMargenes, datos: renderDatos }[state.tab];
      content.appendChild(fn());
    }
    render();
    return { goTo: go, state: state };
  }

  function mountFromUrl(root, url, opts) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(function (d) { return mount(root, d, opts); });
  }
  global.ProyeccionDashboard = { mount: mount, mountFromUrl: mountFromUrl, version: VERSION };
})(typeof window !== 'undefined' ? window : this);
