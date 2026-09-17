/**
 * Control de planchas de sublimación (Ayala Core) para "VENTAS POR
 * CANALES MATIAS", pestaña "ERP AYALA" -- Parte 1 (base MLA +
 * desplegables) y Parte 2 (precio en vivo puntual), pedido de Maxx
 * 2026-09-16.
 *
 * Este script NO tiene credenciales de Mercado Libre. Todo lo que
 * necesita de ML le llega vía HTTP al backend del ERP (Railway), que ya
 * tiene los tokens y ya resuelve la detección de condición / precio real
 * -- ver `ayala_core.descubrir_publicaciones_base` y `ayala_core.
 * precio_vivo_mlas` en el repo del ERP.
 *
 * Instalación (una sola vez):
 *   1. En el Sheet "VENTAS POR CANALES MATIAS" -> Extensiones -> Apps
 *      Script.
 *   2. Pegar TODO este archivo en Codigo.gs (reemplazando lo que haya).
 *   3. Guardar (el ícono de disquete o Ctrl+S).
 *   4. Volver al Sheet y refrescar la página -- va a aparecer un menú
 *      nuevo "Ayala Core" en la barra de arriba.
 *   5. Menú "Ayala Core" -> "Actualizar base MLA" (primera vez tarda un
 *      poco más porque además te va a pedir autorizar el script -- es
 *      normal, aceptá los permisos de "ver y administrar esta hoja").
 *   6. Menú "Ayala Core" -> "Configurar desplegables".
 *
 * De ahí en más, elegir una Condición en la columna M de una fila
 * MT/IT ya filtra solo los MLA correspondientes en la columna N de al
 * lado.
 *
 * Precio en vivo (Parte 2), parado en cualquier fila MT/IT con MLA ya
 * elegido en N:
 *   - Menú "Ayala Core" -> "Traer precio en vivo (fila actual)": escribe
 *     precio actual / tachado / descuento % de ESE MLA en O/P/Q.
 *   - Menú "Ayala Core" -> "Ver todos los precios de esta condición":
 *     popup con el precio en vivo de TODOS los MLA de esa SKU+Condición+
 *     Cuenta (sin escribir nada en la hoja).
 *   - Menú "Ayala Core" -> "Actualizar precios en Base MLA (todas)":
 *     trae el precio en vivo de TODA la pestaña "Base MLA" (las ~109
 *     publicaciones, no una fila puntual) y lo escribe ahí mismo en
 *     columnas F-I. Tarda más (llama a ML una vez por publicación) --
 *     pensado para correr de vez en cuando, no en cada edición.
 * No se dispara solo al elegir en el desplegable -- Apps Script no deja
 * que un simple trigger llame al backend, así que es siempre por menú.
 */

// ── Configuración ──

var BACKEND_URL = 'https://ayala-s-erp-production.up.railway.app';
var HOJA_ERP = 'ERP AYALA';
var HOJA_BASE = 'Base MLA';
var COL_CONDICION = 13; // M
var COL_MLA = 14;       // N
var COL_PRECIO_ACTUAL = 15; // O -- Parte 2
var COL_TACHADO = 16;       // P -- Parte 2
var COL_DESCUENTO = 17;     // Q -- Parte 2

// Columnas F-I de "Base MLA" -- Parte 2b (2026-09-17): precio en vivo de
// TODAS las publicaciones de la base, no solo la fila que estás mirando en
// "ERP AYALA". A/B/C/D/E (SKU/Condición/Cuenta/MLA/Link) ya las escribe
// _escribirBaseMLA -- estas se agregan aparte, en una pasada propia.
var COL_BASE_PRECIO_ACTUAL = 6; // F
var COL_BASE_TACHADO = 7;       // G
var COL_BASE_DESCUENTO = 8;     // H
var COL_BASE_CONDICION_LIVE = 9;// I
// El endpoint de precio en vivo hace una llamada a ML por publicación, en
// serie -- de a lotes de a lo sumo esto por pedido, para que ningún HTTP
// individual quede tan largo que arriesgue timeout, y para no perder TODO
// el progreso si un lote falla a mitad de camino.
var TAMANO_LOTE_PRECIO_VIVO = 25;

// Traduce el valor crudo que devuelve el backend ("contado","reducida",
// "3","6","9","12") a la misma etiqueta que ya usan los encabezados de
// "ERP AYALA" (fila 1, columnas D a I) -- así el filtro compara texto
// contra texto sin traducir nada en el momento.
var ETIQUETA_CONDICION = {
  'contado': 'Contado', 'reducida': 'Reducida',
  '3': '3 cuotas', '6': '6 cuotas', '9': '9 cuotas', '12': '12 cuotas',
};
var CONDICIONES_DROPDOWN = ['Contado', 'Reducida', '3 cuotas', '6 cuotas', '9 cuotas', '12 cuotas'];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Ayala Core')
    .addItem('Actualizar base MLA', 'actualizarBaseMLA')
    .addItem('Configurar desplegables', 'configurarDesplegables')
    .addSeparator()
    .addItem('Traer precio en vivo (fila actual)', 'traerPrecioVivoFilaActual')
    .addItem('Ver todos los precios de esta condición', 'verTodosPreciosCondicion')
    .addItem('Actualizar precios en Base MLA (todas)', 'actualizarPreciosBaseMLA')
    .addToUi();
}

// ── Parte 1a: pestaña "Base MLA" ──

/**
 * Pide al backend el mapeo SKU/condición/cuenta/MLA/link (escanea TODAS
 * las publicaciones activas de las dos cuentas, se queda con los SKU
 * piloto) y reescribe la pestaña "Base MLA" con el resultado fresco.
 * No toca "ERP AYALA" -- eso es "Configurar desplegables", aparte.
 */
function actualizarBaseMLA() {
  var ui = SpreadsheetApp.getUi();
  try {
    var jobId = _iniciarJobBaseMLA();
    var resultado = _esperarJob('/ayala-core/base-mla/status/', jobId);
    var filas = resultado.filas || [];
    _escribirBaseMLA(filas);
    ui.alert('Base MLA actualizada: ' + filas.length + ' publicaciones.');
  } catch (e) {
    ui.alert('Error actualizando la base: ' + e.message);
  }
}

function _iniciarJobBaseMLA() {
  var res = UrlFetchApp.fetch(BACKEND_URL + '/ayala-core/base-mla/run', {
    method: 'post', muteHttpExceptions: true,
  });
  var body = JSON.parse(res.getContentText());
  if (!body.job_id) throw new Error('El backend no devolvió job_id: ' + res.getContentText());
  return body.job_id;
}

// Sondea el status del job cada 5s hasta "done"/"error", con un máximo
// de intentos para no colgar el script (Apps Script corta a los 6 min
// de ejecución igual, esto es para no llegar a ese límite en silencio).
function _esperarJob(pathStatus, jobId) {
  var intentos = 0;
  while (intentos < 60) { // ~5 minutos
    var res = UrlFetchApp.fetch(BACKEND_URL + pathStatus + jobId, { muteHttpExceptions: true });
    var data = JSON.parse(res.getContentText());
    if (data.status === 'done') return data.result;
    if (data.status === 'error') throw new Error(data.log ? data.log.join(' | ') : 'Error desconocido del job');
    Utilities.sleep(5000);
    intentos++;
  }
  throw new Error('El job no terminó a tiempo (más de 5 minutos) -- probá de nuevo en un rato.');
}

function _escribirBaseMLA(filas) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var hoja = ss.getSheetByName(HOJA_BASE);
  if (!hoja) {
    hoja = ss.insertSheet(HOJA_BASE);
    hoja.hideSheet();
  }
  hoja.clearContents();
  var encabezado = ['SKU', 'Condición', 'Cuenta', 'MLA', 'Link'];
  var filasSalida = filas.map(function (f) {
    return [
      f.sku,
      ETIQUETA_CONDICION[String(f.condicion)] || f.condicion,
      f.cuenta,
      f.item_id,
      f.permalink || ('https://articulo.mercadolibre.com.ar/' + f.item_id),
    ];
  });
  hoja.getRange(1, 1, 1, encabezado.length).setValues([encabezado]);
  if (filasSalida.length) {
    hoja.getRange(2, 1, filasSalida.length, encabezado.length).setValues(filasSalida);
  }
}

// ── Parte 1b: desplegables en "ERP AYALA" ──

/**
 * Recorre "ERP AYALA" de punta a punta, identifica cada fila MT/IT
 * (columna A = "Publicaciones" para MT, columna B = "IT" con columna A
 * vacía para IT) y le pone el desplegable fijo de Condición en la
 * columna M. La columna N (MLA) se deja sin validación fija -- se arma
 * sola, filtrada, cuando cambiás M (ver onEdit más abajo).
 */
function configurarDesplegables() {
  var hoja = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HOJA_ERP);
  if (!hoja) { SpreadsheetApp.getUi().alert('No encontré la pestaña "' + HOJA_ERP + '"'); return; }
  var datos = hoja.getDataRange().getValues();
  var reglaCondicion = SpreadsheetApp.newDataValidation()
    .requireValueInList(CONDICIONES_DROPDOWN, true)
    .setAllowInvalid(false)
    .build();
  var filasConfiguradas = 0;
  for (var i = 0; i < datos.length; i++) {
    var esMT = datos[i][0] === 'Publicaciones';
    var esIT = datos[i][0] === '' && datos[i][1] === 'IT';
    if (!esMT && !esIT) continue;
    hoja.getRange(i + 1, COL_CONDICION).setDataValidation(reglaCondicion);
    filasConfiguradas++;
  }
  SpreadsheetApp.getUi().alert('Desplegable de Condición configurado en ' + filasConfiguradas + ' filas (MT/IT). Elegí una condición para que se filtre el MLA al lado.');
}

/**
 * Simple trigger -- se dispara solo al editar cualquier celda del Sheet.
 * Cuando la edición cae en la columna M (Condición) de una fila MT/IT
 * de "ERP AYALA", recalcula la lista de MLA válidos (columna N) contra
 * "Base MLA", filtrando por SKU del bloque + Condición elegida + Cuenta
 * de esa fila (MT o IT, no se pregunta -- ya está en la columna B).
 */
function onEdit(e) {
  var hoja = e.range.getSheet();
  if (hoja.getName() !== HOJA_ERP) return;
  if (e.range.getColumn() !== COL_CONDICION) return;

  var fila = e.range.getRow();
  var sku = _skuDelBloque(hoja, fila);
  var cuenta = hoja.getRange(fila, 2).getValue(); // columna B: "MT" o "IT"
  var condicion = e.value;
  if (!sku || !cuenta || !condicion) return;

  var mlas = _mlasFiltrados(sku, condicion, cuenta);
  var celdaMLA = hoja.getRange(fila, COL_MLA);
  if (!mlas.length) {
    celdaMLA.clearDataValidations();
    celdaMLA.setValue('(sin MLA para esa combinación)');
    return;
  }
  var regla = SpreadsheetApp.newDataValidation().requireValueInList(mlas, true).setAllowInvalid(false).build();
  celdaMLA.setDataValidation(regla);
  celdaMLA.setValue(mlas[0]); // preselecciona el primero, se puede cambiar si hay más de uno
}

// Sube desde `fila` hasta encontrar la fila con columna A = "SKU" (el
// encabezado del bloque) y devuelve su columna B -- el bloque es siempre
// SKU / Publicaciones(MT) / IT, en ese orden, así que nunca hay que subir
// más de 2 filas.
function _skuDelBloque(hoja, fila) {
  for (var f = fila; f >= 1; f--) {
    if (hoja.getRange(f, 1).getValue() === 'SKU') {
      return hoja.getRange(f, 2).getValue();
    }
  }
  return null;
}

function _mlasFiltrados(sku, condicionEtiqueta, cuenta) {
  var hojaBase = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HOJA_BASE);
  if (!hojaBase) return [];
  var datos = hojaBase.getDataRange().getValues(); // [SKU, Condición, Cuenta, MLA, Link]
  var resultado = [];
  for (var i = 1; i < datos.length; i++) {
    if (datos[i][0] === sku && datos[i][1] === condicionEtiqueta && datos[i][2] === cuenta) {
      resultado.push(datos[i][3]);
    }
  }
  return resultado;
}

// ── Parte 2: precio en vivo puntual ──
//
// Nunca se dispara solo -- Apps Script no deja que un simple trigger
// (onEdit) llame a UrlFetchApp, aunque el script ya esté autorizado, así
// que esto va por menú, no por elegir en el desplegable. Las dos
// acciones ("una fila" / "ver todas") comparten `_fetchPrecioVivo`, que
// es el mismo endpoint (`/ayala-core/mla/precio-vivo`) aceptando una
// lista de 1 o de N -- ver `precio_vivo_mlas` en el backend.

/**
 * Trae el precio en vivo del MLA que ya está elegido en la columna N de
 * la fila donde tenés el cursor, y lo escribe en O (Precio actual), P
 * (Tachado) y Q (Descuento %) de esa misma fila.
 */
function traerPrecioVivoFilaActual() {
  var ui = SpreadsheetApp.getUi();
  var hoja = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  if (hoja.getName() !== HOJA_ERP) { ui.alert('Parate en una fila de "' + HOJA_ERP + '" primero.'); return; }

  var fila = SpreadsheetApp.getActiveSpreadsheet().getActiveRange().getRow();
  var mla = String(hoja.getRange(fila, COL_MLA).getValue()).trim();
  if (!/^MLA/i.test(mla)) { ui.alert('La columna N de esta fila no tiene un MLA elegido todavía.'); return; }

  try {
    var cuenta = hoja.getRange(fila, 2).getValue();
    var resultados = _fetchPrecioVivo([mla], cuenta);
    var r = resultados[0];
    if (!r || r.error) { ui.alert('No se pudo traer el precio: ' + (r ? r.error : 'sin respuesta')); return; }
    hoja.getRange(fila, COL_PRECIO_ACTUAL).setValue(r.precio_actual);
    hoja.getRange(fila, COL_TACHADO).setValue(r.precio_tachado || '');
    hoja.getRange(fila, COL_DESCUENTO).setValue(r.descuento_pct !== null && r.descuento_pct !== undefined ? r.descuento_pct / 100 : '');
  } catch (e) {
    ui.alert('Error trayendo el precio en vivo: ' + e.message);
  }
}

/**
 * Junta TODOS los MLA de la SKU + Condición + Cuenta de la fila actual
 * (mismo filtro que ya arma la columna N, vía `_mlasFiltrados`) y
 * muestra el precio en vivo de cada uno en un popup -- son 2-3 publicaciones
 * como mucho, no hace falta escribir nada en la hoja para compararlas.
 */
function verTodosPreciosCondicion() {
  var ui = SpreadsheetApp.getUi();
  var hoja = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  if (hoja.getName() !== HOJA_ERP) { ui.alert('Parate en una fila de "' + HOJA_ERP + '" primero.'); return; }

  var fila = SpreadsheetApp.getActiveSpreadsheet().getActiveRange().getRow();
  var sku = _skuDelBloque(hoja, fila);
  var cuenta = hoja.getRange(fila, 2).getValue();
  var condicion = hoja.getRange(fila, COL_CONDICION).getValue();
  if (!sku || !cuenta || !condicion) { ui.alert('Esta fila no tiene SKU/Cuenta/Condición completos.'); return; }

  var mlas = _mlasFiltrados(sku, condicion, cuenta);
  if (!mlas.length) { ui.alert('No hay MLA para ' + sku + ' / ' + condicion + ' / ' + cuenta + '.'); return; }

  try {
    var resultados = _fetchPrecioVivo(mlas, cuenta);
    var lineas = resultados.map(function (r) {
      if (r.error) return r.item_id + ': error -- ' + r.error;
      var linea = r.item_id + ': ' + _formatoPesos(r.precio_actual);
      if (r.precio_tachado) linea += ' (tachado ' + _formatoPesos(r.precio_tachado) + ', -' + r.descuento_pct + '%)';
      linea += ' -- condición detectada: ' + r.condicion_detectada;
      return linea;
    });
    ui.alert(sku + ' / ' + condicion + ' / ' + cuenta, lineas.join('\n'), ui.ButtonSet.OK);
  } catch (e) {
    ui.alert('Error trayendo los precios en vivo: ' + e.message);
  }
}

/**
 * Trae el precio en vivo de TODAS las publicaciones que ya están en "Base
 * MLA" (no una fila puntual) y lo escribe ahí mismo, en columnas F (Precio
 * actual), G (Tachado), H (Descuento %), I (Condición detectada) --
 * pedido de Maxx 2026-09-17: "necesitamos uno que ponga todos los datos
 * que necesitamos en las celdas, pero en la pestaña de Base MLA" (a
 * diferencia de "Ver todos los precios de esta condición", que solo
 * muestra un popup de una SKU+Condición+Cuenta puntual, sin persistir
 * nada). No vuelve a pedir el mapeo SKU/MLA -- reusa lo que ya haya en A-E
 * (correlo después de "Actualizar base MLA" si querés la lista más
 * fresca posible).
 */
function actualizarPreciosBaseMLA() {
  var ui = SpreadsheetApp.getUi();
  var hoja = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HOJA_BASE);
  if (!hoja) { ui.alert('No encontré la pestaña "' + HOJA_BASE + '" -- corré primero "Actualizar base MLA".'); return; }
  var datos = hoja.getDataRange().getValues(); // [SKU, Condición, Cuenta, MLA, Link, ...]
  if (datos.length < 2) { ui.alert('"' + HOJA_BASE + '" está vacía -- corré primero "Actualizar base MLA".'); return; }

  // El endpoint pide una sola cuenta por llamada -- agrupamos los MLA por
  // cuenta acá, no por SKU/Condición (a este endpoint no le importan).
  var mlasPorCuenta = {};
  for (var i = 1; i < datos.length; i++) {
    var mla = datos[i][3], cuenta = datos[i][2];
    if (!mla || !cuenta) continue;
    (mlasPorCuenta[cuenta] = mlasPorCuenta[cuenta] || []).push(mla);
  }

  var resultadoPorMLA = {};
  try {
    for (var cuenta in mlasPorCuenta) {
      var ids = mlasPorCuenta[cuenta];
      for (var i = 0; i < ids.length; i += TAMANO_LOTE_PRECIO_VIVO) {
        var lote = ids.slice(i, i + TAMANO_LOTE_PRECIO_VIVO);
        var resultados = _fetchPrecioVivo(lote, cuenta);
        resultados.forEach(function (r) { resultadoPorMLA[r.item_id] = r; });
      }
    }
  } catch (e) {
    ui.alert('Error trayendo precios (se cortó a mitad de camino, nada se escribió todavía): ' + e.message);
    return;
  }

  var encabezado = datos[0].slice(0, 5).concat(['Precio actual', 'Tachado', 'Descuento %', 'Condición detectada']);
  var filasSalida = [];
  var errores = 0;
  for (var i = 1; i < datos.length; i++) {
    var base = datos[i].slice(0, 5);
    var r = resultadoPorMLA[datos[i][3]];
    if (!r || r.error) {
      errores += r ? 1 : 0;
      filasSalida.push(base.concat(['', '', '', r ? ('Error: ' + r.error) : '']));
      continue;
    }
    filasSalida.push(base.concat([
      r.precio_actual,
      r.precio_tachado || '',
      r.descuento_pct != null ? r.descuento_pct / 100 : '',
      ETIQUETA_CONDICION[String(r.condicion_detectada)] || r.condicion_detectada,
    ]));
  }

  hoja.getRange(1, 1, 1, encabezado.length).setValues([encabezado]);
  hoja.getRange(2, 1, filasSalida.length, encabezado.length).setValues(filasSalida);
  ui.alert('Precios actualizados en "' + HOJA_BASE + '": ' + filasSalida.length + ' publicaciones' + (errores ? (', ' + errores + ' con error (ver columna "Condición detectada")') : '') + '.');
}

function _fetchPrecioVivo(itemIds, cuenta) {
  var url = BACKEND_URL + '/ayala-core/mla/precio-vivo?item_ids=' + encodeURIComponent(itemIds.join(','))
    + '&cuenta=' + encodeURIComponent(cuenta);
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) throw new Error('Backend respondió ' + res.getResponseCode() + ': ' + res.getContentText());
  var body = JSON.parse(res.getContentText());
  return body.resultados || [];
}

function _formatoPesos(valor) {
  return '$' + Math.round(valor).toLocaleString('es-AR');
}
