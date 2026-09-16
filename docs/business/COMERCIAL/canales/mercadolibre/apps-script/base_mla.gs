/**
 * Control de planchas de sublimación (Ayala Core) para "VENTAS POR
 * CANALES MATIAS", pestaña "ERP AYALA" -- Parte 1, paso 1 (pedido de
 * Maxx 2026-09-16).
 *
 * Este script NO tiene credenciales de Mercado Libre. Todo lo que
 * necesita de ML le llega vía HTTP al backend del ERP (Railway), que ya
 * tiene los tokens y ya resuelve la detección de condición / precio real
 * -- ver `ayala_core.descubrir_publicaciones_base` en el repo del ERP.
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
 */

// ── Configuración ──

var BACKEND_URL = 'https://ayala-s-erp-production.up.railway.app';
var HOJA_ERP = 'ERP AYALA';
var HOJA_BASE = 'Base MLA';
var COL_CONDICION = 13; // M
var COL_MLA = 14;       // N

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
