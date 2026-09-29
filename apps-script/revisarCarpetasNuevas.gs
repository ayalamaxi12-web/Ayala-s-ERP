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
 * carpeta como hacía DriveApp.getFolders(), y la profundidad está acotada por MAX_PROFUNDIDAD.
 * Se filtra por createdTime para avisar solo las nuevas y se guardan los ids ya avisados para no
 * repetir mails.
 *
 * Requisitos: servicio avanzado "Drive API" (v3) activado (Editor > Servicios > Drive API) — ya está
 * declarado en appsscript.json. Correr instalarTrigger() una vez.
 */

const FOLDER_ID = '1Blsb4o2HSNcpYXag0cVSg3teFoPmChNY'; // ML GLOBAL
const NOTIFICAR_A = 'CAMBIAR@globalecom.ar';           // varios: separados por coma
const MAX_PROFUNDIDAD = 3;       // 1 = solo hijas directas de ML GLOBAL; 3 = hasta nietas de nietas
const MARGEN_MIN = 15;           // se re-mira este margen hacia atrás por demoras de indexado (no duplica: hay dedupe)
const LIMITE_MS = 4.5 * 60 * 1000; // corta antes de los 6 min de Apps Script
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
      console.log('Primera ejecución: se toma ' + inicio.toISOString() + ' como punto de partida (no se avisa lo existente).');
      return;
    }
    const desde = new Date(new Date(ultima).getTime() - MARGEN_MIN * 60000);
    const avisadas = JSON.parse(props.getProperty('AVISADAS') || '{}'); // id -> ms en que se avisó

    const r = buscarCarpetas_(desde, inicio.getTime());
    const nuevas = r.carpetas.filter(c => !avisadas[c.id]);
    console.log('Revisadas ' + r.revisadas + ' carpetas en ' + r.niveles + ' nivel(es), ' + r.llamadas + ' llamadas. Nuevas: ' + nuevas.length + (r.completo ? '' : ' (INCOMPLETO por tiempo)'));

    if (nuevas.length) {
      enviarMail_(nuevas);
      nuevas.forEach(c => avisadas[c.id] = inicio.getTime());
    }
    // Olvidar avisos viejos (y acotar tamaño: una propiedad soporta ~9 KB).
    const corte = inicio.getTime() - DIAS_RECORDAR * 86400000;
    const ids = Object.keys(avisadas).filter(id => avisadas[id] >= corte).sort((a, b) => avisadas[b] - avisadas[a]).slice(0, 250);
    const limpias = {}; ids.forEach(id => limpias[id] = avisadas[id]);
    props.setProperty('AVISADAS', JSON.stringify(limpias));

    // Si no se llegó a recorrer todo, no se avanza la fecha: la próxima corrida vuelve a mirar
    // desde el mismo punto y el dedupe evita avisar dos veces lo que ya salió.
    if (r.completo) props.setProperty('ULTIMA_REVISION', inicio.toISOString());
  } finally {
    lock.releaseLock();
  }
}

/** Recorre ML GLOBAL por niveles y devuelve las carpetas creadas desde `desde`. */
function buscarCarpetas_(desde, t0) {
  const rutas = {}; rutas[FOLDER_ID] = 'ML GLOBAL';
  const vistas = {}; vistas[FOLDER_ID] = true;
  const carpetas = [];
  let nivel = [FOLDER_ID], niveles = 0, revisadas = 0, llamadas = 0, completo = true;
  while (nivel.length && niveles < MAX_PROFUNDIDAD && completo) {
    niveles++;
    const siguiente = [];
    for (let i = 0; i < nivel.length; i += PADRES_POR_CONSULTA) {
      if (Date.now() - t0 > LIMITE_MS) { completo = false; break; }
      const lote = nivel.slice(i, i + PADRES_POR_CONSULTA);
      const q = '(' + lote.map(id => "'" + id + "' in parents").join(' or ') + ") and mimeType='" + FOLDER_MIME + "' and trashed=false";
      const res = listarTodo_(q);
      llamadas += res.llamadas;
      res.files.forEach(f => {
        if (vistas[f.id]) return;
        vistas[f.id] = true; revisadas++;
        const padre = (f.parents || []).find(p => lote.indexOf(p) >= 0) || lote[0];
        rutas[f.id] = rutas[padre] + ' / ' + f.name;
        siguiente.push(f.id);
        if (new Date(f.createdTime) >= desde) {
          const u = (f.owners && f.owners[0]) || f.lastModifyingUser || {}; // en unidades compartidas no hay owners
          carpetas.push({ id: f.id, nombre: f.name, ruta: rutas[f.id], creada: new Date(f.createdTime),
                          autor: u.displayName || u.emailAddress || '(desconocido)', email: u.emailAddress || '',
                          link: f.webViewLink || ('https://drive.google.com/drive/folders/' + f.id) });
        }
      });
    }
    nivel = siguiente;
  }
  return { carpetas, revisadas, niveles, llamadas, completo };
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
  const r = buscarCarpetas_(new Date(t0 - dias * 86400000), t0);
  console.log('Revisadas ' + r.revisadas + ' carpetas, ' + r.llamadas + ' llamadas, ' + ((Date.now() - t0) / 1000).toFixed(1) + ' s' + (r.completo ? '' : ' (INCOMPLETO)'));
  r.carpetas.forEach(c => console.log(c.creada.toISOString() + ' | ' + c.autor + ' | ' + c.ruta));
}

/** Borra el estado guardado (la próxima corrida arranca de cero, sin avisar lo existente). */
function resetearEstado() {
  PropertiesService.getScriptProperties().deleteProperty('ULTIMA_REVISION');
  PropertiesService.getScriptProperties().deleteProperty('AVISADAS');
}
