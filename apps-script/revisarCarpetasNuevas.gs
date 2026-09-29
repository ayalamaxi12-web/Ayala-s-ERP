/**
 * revisarCarpetasNuevas — avisa por mail cuando aparece una carpeta nueva dentro de ML GLOBAL,
 * la haya creado quien la haya creado.
 *
 * Por qué no alcanzaba DriveApp.searchFolders: la búsqueda "global" de Drive solo mira el corpus
 * del usuario (lo que creó, abrió o le compartieron DIRECTAMENTE). Una carpeta que otra persona crea
 * adentro de una carpeta compartida hereda el acceso pero no entra en ese corpus hasta que la abrís,
 * así que la búsqueda por fecha no la devuelve. Las consultas por padre ('<id>' in parents) sí listan
 * todos los hijos a los que tenés acceso, sin importar el dueño.
 *
 * Estrategia: recorrer ML GLOBAL por niveles con la API avanzada de Drive (v3), pidiendo los hijos de
 * hasta PADRES_POR_CONSULTA carpetas en UNA sola llamada ('a' in parents or 'b' in parents ...), solo
 * carpetas y solo los campos necesarios. Eso es 1 llamada por cada ~40 carpetas en vez de 1 por
 * carpeta como hacía DriveApp.getFolders(). Recorre todo el árbol (sin límite de profundidad, salvo
 * que se fije MAX_PROFUNDIDAD); si el árbol es tan grande que no entra en una corrida, guarda lo que
 * falta y sigue en la próxima, sin pasarse nunca de los 6 minutos.
 * Se filtra por createdTime para avisar solo las nuevas y se guardan los ids ya avisados para no
 * repetir mails.
 *
 * Requisitos: servicio avanzado "Drive API" (v3) activado (Editor > Servicios > Drive API) — ya está
 * declarado en appsscript.json. Correr instalarTrigger() una vez.
 */

const FOLDER_ID = '1Blsb4o2HSNcpYXag0cVSg3teFoPmChNY'; // ML GLOBAL
const NOTIFICAR_A = 'CAMBIAR@globalecom.ar';           // varios: separados por coma
const MAX_PROFUNDIDAD = 0;       // 0 = sin límite (todo el árbol); 1 = solo hijas directas de ML GLOBAL
const MARGEN_MIN = 15;           // se re-mira este margen hacia atrás por demoras de indexado (no duplica: hay dedupe)
const LIMITE_MS = 4.5 * 60 * 1000; // corta antes de los 6 min de Apps Script y sigue en la próxima corrida
const PADRES_POR_CONSULTA = 40;  // carpetas padre por llamada a Drive.Files.list
const DIAS_RECORDAR = 7;         // cuánto tiempo se recuerdan los ids ya avisados
const FOLDER_MIME = 'application/vnd.google-apps.folder';
const CAMPOS = 'nextPageToken, incompleteSearch, files(id,name,createdTime,parents,webViewLink,owners(displayName,emailAddress),lastModifyingUser(displayName,emailAddress))';

function revisarCarpetasNuevas() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) { console.log('Otra ejecución en curso, salgo.'); return; }
  try {
    const props = PropertiesService.getScriptProperties();
    const inicio = new Date();
    const ultima = props.getProperty('ULTIMA_REVISION');
    if (!ultima) {
      props.setProperty('ULTIMA_REVISION', inicio.toISOString());
      borrarPendiente_();
      console.log('Primera ejecución: se toma ' + inicio.toISOString() + ' como punto de partida (no se avisa lo existente).');
      return;
    }
    // Si la corrida anterior no llegó a recorrer todo el árbol, se sigue desde donde quedó.
    const pend = leerPendiente_();
    const desde = new Date(new Date(ultima).getTime() - MARGEN_MIN * 60000);
    const cola = pend ? pend.cola : [{ id: FOLDER_ID, r: 'ML GLOBAL', d: 0 }];
    const inicioBarrido = pend ? pend.inicio : inicio.toISOString();
    const avisadas = JSON.parse(props.getProperty('AVISADAS') || '{}'); // id -> ms en que se avisó

    const r = buscarCarpetas_(desde, inicio.getTime(), cola);
    const nuevas = r.carpetas.filter(c => !avisadas[c.id]);
    console.log((pend ? 'Continuación: ' : '') + 'revisadas ' + r.revisadas + ' carpetas, ' + r.llamadas + ' llamadas. Nuevas: ' + nuevas.length +
                (r.cola.length ? ' — quedan ' + r.cola.length + ' carpetas por revisar, sigue en la próxima corrida' : ''));

    if (nuevas.length) {
      enviarMail_(nuevas);
      nuevas.forEach(c => avisadas[c.id] = inicio.getTime());
    }
    // Olvidar avisos viejos (y acotar tamaño: una propiedad soporta ~9 KB).
    const corte = inicio.getTime() - DIAS_RECORDAR * 86400000;
    const ids = Object.keys(avisadas).filter(id => avisadas[id] >= corte).sort((a, b) => avisadas[b] - avisadas[a]).slice(0, 250);
    const limpias = {}; ids.forEach(id => limpias[id] = avisadas[id]);
    props.setProperty('AVISADAS', JSON.stringify(limpias));

    if (r.cola.length) {
      // No se avanza ULTIMA_REVISION hasta terminar el barrido. Si el pendiente se pierde (el caché
      // expira), el barrido arranca de nuevo con la misma fecha: no se pierde nada, y el dedupe
      // evita avisar dos veces.
      guardarPendiente_({ inicio: inicioBarrido, cola: r.cola });
    } else {
      borrarPendiente_();
      props.setProperty('ULTIMA_REVISION', inicioBarrido);
    }
  } finally {
    lock.releaseLock();
  }
}

/** Recorre el árbol desde `cola` (FIFO de {id, r: ruta, d: profundidad}) y devuelve las carpetas creadas
 *  desde `desde`, más lo que quedó sin revisar si se acabó el tiempo. */
function buscarCarpetas_(desde, t0, cola) {
  cola = cola.slice();
  const carpetas = [];
  let revisadas = 0, llamadas = 0;
  while (cola.length) {
    if (Date.now() - t0 > LIMITE_MS) break;
    const lote = cola.splice(0, PADRES_POR_CONSULTA);
    const porId = {}; lote.forEach(p => porId[p.id] = p);
    const q = '(' + lote.map(p => "'" + p.id + "' in parents").join(' or ') + ") and mimeType='" + FOLDER_MIME + "' and trashed=false";
    let res;
    try { res = listarTodo_(q); }
    catch (e) { cola.unshift.apply(cola, lote); throw e; }
    llamadas += res.llamadas;
    res.files.forEach(f => {
      const padre = porId[(f.parents || []).find(id => porId[id])] || lote[0];
      const ruta = padre.r + ' / ' + f.name, d = padre.d + 1;
      revisadas++;
      if (!MAX_PROFUNDIDAD || d < MAX_PROFUNDIDAD) cola.push({ id: f.id, r: ruta, d: d });
      if (new Date(f.createdTime) >= desde) {
        const u = (f.owners && f.owners[0]) || f.lastModifyingUser || {}; // en unidades compartidas no hay owners
        carpetas.push({ id: f.id, nombre: f.name, ruta: ruta, creada: new Date(f.createdTime),
                        autor: u.displayName || u.emailAddress || '(desconocido)', email: u.emailAddress || '',
                        link: f.webViewLink || ('https://drive.google.com/drive/folders/' + f.id) });
      }
    });
  }
  return { carpetas, cola, revisadas, llamadas };
}

// El barrido pendiente se guarda en CacheService (hasta 100 KB por clave, se parte en trozos).
const PEND_KEY = 'RCN_PEND', PEND_TROZO = 90000, PEND_MAX_TROZOS = 50;

function guardarPendiente_(p) {
  const json = JSON.stringify(p), n = Math.ceil(json.length / PEND_TROZO);
  if (n > PEND_MAX_TROZOS) { console.warn('Pendiente demasiado grande para guardar; la próxima corrida reinicia el barrido.'); borrarPendiente_(); return; }
  const vals = {}; vals[PEND_KEY] = String(n);
  for (let i = 0; i < n; i++) vals[PEND_KEY + '_' + i] = json.slice(i * PEND_TROZO, (i + 1) * PEND_TROZO);
  CacheService.getScriptCache().putAll(vals, 21600); // 6 h
}

function leerPendiente_() {
  const cache = CacheService.getScriptCache(), n = parseInt(cache.get(PEND_KEY), 10);
  if (!n) return null;
  const keys = []; for (let i = 0; i < n; i++) keys.push(PEND_KEY + '_' + i);
  const vals = cache.getAll(keys);
  if (keys.some(k => vals[k] == null)) return null; // se perdió un trozo: se reinicia el barrido
  try { return JSON.parse(keys.map(k => vals[k]).join('')); } catch (e) { return null; }
}

function borrarPendiente_() {
  const keys = [PEND_KEY]; for (let i = 0; i < PEND_MAX_TROZOS; i++) keys.push(PEND_KEY + '_' + i);
  CacheService.getScriptCache().removeAll(keys);
}

/** Drive.Files.list paginado, incluyendo ítems de otros dueños y de unidades compartidas. */
function listarTodo_(q) {
  const files = []; let token, llamadas = 0;
  do {
    const r = conReintentos_(() => Drive.Files.list({
      q: q, fields: CAMPOS, pageSize: 1000, pageToken: token,
      corpora: 'allDrives', supportsAllDrives: true, includeItemsFromAllDrives: true
    }));
    llamadas++;
    if (r.incompleteSearch) console.warn('Drive devolvió incompleteSearch para: ' + q.slice(0, 120));
    (r.files || []).forEach(f => files.push(f));
    token = r.nextPageToken;
  } while (token);
  return { files, llamadas };
}

function conReintentos_(fn) {
  for (let i = 0; ; i++) {
    try { return fn(); }
    catch (e) {
      if (i >= 3) throw e;
      console.warn('Reintento ' + (i + 1) + ': ' + e.message);
      Utilities.sleep(1000 * Math.pow(2, i));
    }
  }
}

function enviarMail_(nuevas) {
  const tz = Session.getScriptTimeZone();
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  nuevas.sort((a, b) => a.creada - b.creada);
  const filas = nuevas.map(c =>
    '<tr><td style="padding:4px 8px"><a href="' + esc(c.link) + '">' + esc(c.nombre) + '</a></td>' +
    '<td style="padding:4px 8px;color:#555">' + esc(c.ruta) + '</td>' +
    '<td style="padding:4px 8px">' + esc(c.autor) + '</td>' +
    '<td style="padding:4px 8px">' + Utilities.formatDate(c.creada, tz, 'dd/MM/yyyy HH:mm') + '</td></tr>').join('');
  const html = '<p>Se ' + (nuevas.length === 1 ? 'creó 1 carpeta nueva' : 'crearon ' + nuevas.length + ' carpetas nuevas') + ' en ML GLOBAL:</p>' +
    '<table style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px">' +
    '<tr style="background:#f0f0f0"><th style="padding:4px 8px;text-align:left">Carpeta</th><th style="padding:4px 8px;text-align:left">Ruta</th>' +
    '<th style="padding:4px 8px;text-align:left">Creada por</th><th style="padding:4px 8px;text-align:left">Fecha</th></tr>' + filas + '</table>';
  const texto = nuevas.map(c => '- ' + c.ruta + ' (' + c.autor + ', ' + Utilities.formatDate(c.creada, tz, 'dd/MM HH:mm') + ') ' + c.link).join('\n');
  const asunto = nuevas.length === 1 ? 'Nueva carpeta en ML GLOBAL: ' + nuevas[0].nombre : nuevas.length + ' carpetas nuevas en ML GLOBAL';
  MailApp.sendEmail({ to: NOTIFICAR_A, subject: asunto, body: texto, htmlBody: html });
}

// ─── Utilidades (correr a mano desde el editor) ────────────────────────────────────────────────

/** Crea (o recrea) el trigger cada 10 minutos. */
function instalarTrigger() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'revisarCarpetasNuevas').forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('revisarCarpetasNuevas').timeBased().everyMinutes(10).create();
  console.log('Trigger instalado: revisarCarpetasNuevas cada 10 minutos.');
}

/** Solo loguea (no manda mail ni toca el estado) las carpetas creadas en los últimos N días. Sirve
 *  para confirmar que ahora aparecen las que crearon otras personas. */
function diagnostico(dias) {
  dias = dias || 7;
  const t0 = Date.now();
  const r = buscarCarpetas_(new Date(t0 - dias * 86400000), t0, [{ id: FOLDER_ID, r: 'ML GLOBAL', d: 0 }]);
  console.log('Revisadas ' + r.revisadas + ' carpetas, ' + r.llamadas + ' llamadas, ' + ((Date.now() - t0) / 1000).toFixed(1) + ' s' +
              (r.cola.length ? ' (INCOMPLETO: quedaron ' + r.cola.length + ' sin revisar; el trigger lo termina en varias corridas)' : ' — árbol completo'));
  r.carpetas.forEach(c => console.log(c.creada.toISOString() + ' | ' + c.autor + ' | ' + c.ruta));
}

/** Borra el estado guardado (la próxima corrida arranca de cero, sin avisar lo existente). */
function resetearEstado() {
  borrarPendiente_();
  PropertiesService.getScriptProperties().deleteProperty('ULTIMA_REVISION');
  PropertiesService.getScriptProperties().deleteProperty('AVISADAS');
}
