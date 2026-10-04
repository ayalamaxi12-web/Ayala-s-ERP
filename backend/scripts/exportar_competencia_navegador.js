// Pegar en la consola (F12) estando en el ERP, con la API key de Sheets ya cargada en Configuración.
// Solo LEE de Google Sheets y baja UN archivo: competencia_export.json. No escribe nada en ningún lado.
(async () => {
  const KEY = S.sheetsKey, ID = (typeof COMP_SHEET_ID !== 'undefined') ? COMP_SHEET_ID : '15b9kMzQFHdBOE5_7vWgriiiulHI6Yc9upJBUBBiXepY';
  if (!KEY) { console.error('Falta la API key de Sheets (Configuración).'); return; }
  const base = `https://sheets.googleapis.com/v4/spreadsheets/${ID}`;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const get = async p => {
    for (let i = 0; i < 6; i++) {
      const r = await fetch(`${base}${p}${p.includes('?') ? '&' : '?'}key=${KEY}`);
      if (r.status === 429) { await sleep(8000 * (i + 1)); continue; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }
    throw new Error('429 persistente');
  };
  const titles = (await get('?fields=sheets.properties.title')).sheets.map(s => s.properties.title);
  const out = { _exportado: new Date().toISOString(), _pestanas: titles, _errores: [], v_tabs: {} };
  const leer = async (clave, nombre) => {
    if (!titles.includes(nombre)) { out[clave] = []; console.log(`· ${nombre}: no existe (ok, queda vacía)`); return; }
    try { out[clave] = (await get('/values/' + encodeURIComponent(nombre))).values || []; console.log(`✓ ${nombre}: ${out[clave].length} filas`); }
    catch (e) { out[clave] = []; out._errores.push(nombre + ': ' + e.message); console.error(`✗ ${nombre}: ${e.message}`); }
    await sleep(600);
  };
  await leer('refs', 'Referencias_Mercado');
  await leer('ents', 'Entidades');
  await leer('general', 'General');
  await leer('ml_competencia', 'ML Competencia');
  await leer('hist_competidores', 'Historial Competidores');
  await leer('monitor', 'Monitor_Lecturas');
  await leer('historial_existente', 'Historial_Precios');
  await leer('huerfanos_existentes', 'Migracion_Huerfanos');
  for (const t of titles.filter(t => t.startsWith('V - '))) {
    try { out.v_tabs[t] = (await get('/values/' + encodeURIComponent(t))).values || []; console.log(`✓ ${t}: ${out.v_tabs[t].length} filas`); }
    catch (e) { out._errores.push(t + ': ' + e.message); console.error(`✗ ${t}: ${e.message}`); }
    await sleep(600);
  }
  const blob = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'competencia_export.json';
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`LISTO: competencia_export.json (${(blob.size / 1048576).toFixed(1)} MB), ${Object.keys(out.v_tabs).length} pestañas V-*, errores: ${out._errores.length}`);
})();
