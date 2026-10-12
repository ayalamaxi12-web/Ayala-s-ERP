# Costo cacheado (A) y herramientas de pricing dentro de Análisis de Competencia (B) — PLAN, sin construir

## A) Costo de Ecom: una vez por día, guardado, con refresco manual

### Lo que verifiqué en el código
- Todo lo que usa costo pasa por `rentabilidad/costos_ecom.obtener_catalogo()`: `GET /rentabilidad/costos/ecom` (Competidores, Análisis, Ofertas en el front), `CostoEcomProvider` / `IvaConRespaldoEcom`
  (Motor de Precios `/rentabilidad/pricing/*`, Ofertas ML `ml_ofertas`, Ayala Core, `main.py` 2287/2418).
- **Ya existe un caché**, pero solo en memoria del proceso web, con TTL de 1 h y recarga **dentro del request** (`with _lock:` bajando ~115 páginas de a una, ~80 s según la nota del autor).
  Por eso los 80 s reaparecen: (1) cada deploy/reinicio de Railway (hay un precalentado en un hilo, pero si entrás antes de que termine esperás); (2) **cada hora**, cuando vence el TTL: el
  primer request que llega espera los 80 s y los demás quedan bloqueados detrás del mismo lock.
- Un único worker de uvicorn (`entrypoint.sh`): el caché en memoria no se comparte entre procesos y se pierde al reiniciar.
- **Los 80 s son del catálogo de Ecom para la pantalla** (el endpoint solo llama a `obtener_catalogo`). **No pude medirlo yo** (este entorno no tiene acceso a Ecom): el número es el de la nota del autor.
  Para **el motor** (`/pricing/*`) puede haber otra fuente de espera además de Ecom: el IVA de Táctica (SQL por Tailscale, con tiempos de espera si el túnel está caído) y la lectura de GRAL CATEGORIAS.
  Se distingue con una medición (ver abajo).

### Propuesta
1. **Dónde se guarda:** en la base de Rentabilidad (Postgres de Railway, ya usada por el motor), tabla `costo_ecom_snapshot` (`id`, `obtenido_en`, `origen` = cron | manual | arranque, `duracion_seg`, `cantidad`, `error`, `payload` JSON con costos, IVA, ambiguos y sin costo).
   Se conservan los últimos ~7 snapshots (permite ver qué SKU cambió de costo entre uno y otro y volver atrás). Migración Alembic como las demás.
2. **Lectura (lo único que hace un request):** `obtener_catalogo()` devuelve el snapshot más reciente (memoria → si no está, la base; milisegundos) y **nunca descarga de Ecom en un request**. Se re-lee de la base cada ~5 min
   para tomar el snapshot que escribió el cron. Todo lo que usa costo (motor, Ofertas, Ayala Core, Competidores y Análisis vía `/costos/ecom`) queda cubierto con ese único cambio.
3. **Refresco automático a la mañana:** se agrega como primer paso (no fatal) de `scripts/ecom_diario.py`, el cron que ya corre todos los días a las 06:00 hora Argentina (`railway.cron.json`, mismas credenciales de Ecom).
   Respaldo: al arrancar el backend, si el último snapshot tiene más de 24 h (o no existe), se dispara una descarga en segundo plano mientras se sirve el snapshot viejo.
4. **Refresco a mano:** `POST /rentabilidad/costos/ecom/refrescar` (X-ERP-Key; un solo refresco a la vez; devuelve en seguida y corre en segundo plano ~80 s) + `GET /rentabilidad/costos/ecom/estado`
   (antigüedad, en curso, última duración, cantidad, último error). En el front, botón **⟳ Refrescar costos (hace 3 h)** en Análisis, Competidores, Ofertas y Motor de Precios; avisa cuando termina.
   A verificar: si la API GraphQL de Ecom permite pedir un solo SKU, se agrega "refrescar este SKU" (1 llamada) para el caso de una impo nueva; hoy no lo sé.
5. **Si Ecom falla:** se mantiene el snapshot anterior y la pantalla muestra "costos de hace N h" en amarillo si pasaron más de ~36 h. Nunca se vacía.
6. **Medición antes de tocar (para confirmar la causa):** en la consola del ERP, dos veces seguidas:
   `(async()=>{const bu=getBackendUrl();for(let i=0;i<2;i++){const t=performance.now();const d=await(await fetch(bu+'/rentabilidad/costos/ecom')).json();console.log('#'+(i+1),((performance.now()-t)/1000).toFixed(1)+' s',Object.keys(d.costos).length+' SKU','catálogo de hace '+Math.round((Date.now()/1000-d.obtenido_en)/60)+' min');}})()`
   Si la primera tarda y la segunda es instantánea: es la bajada de Ecom. Si con "catálogo de hace 0 min" tarda: acaba de bajar uno (reinicio o hora cumplida).
7. Sub-etapas: **A1** tabla + lectura desde la base + tests; **A2** refresco diario en `ecom_diario.py` + catch-up al arrancar + endpoints manual/estado; **A3** botón y antigüedad en las 4 pantallas.

## B) Herramientas de pricing dentro de Análisis de Competencia

### Qué existe hoy (y se reusa, no se reescribe)
| Herramienta | Dónde | Endpoint / función |
|---|---|---|
| Modificar precio de sistema (lista "Mercado Libre" de Ecom) | Competidores (`compModEcom`), Verificar Ecom (`fixOneEcom`) | `POST /ecom/update-price` (usa la cookie de Ecom del front) |
| Aplicar / sacar oferta ML (precio + tachado, campañas) | Ofertas ML, panel "Gestionar" (`ofmCargarPromociones`, `ofmRenderGestionarPanel`, `ofmSimularActivar`, `ofmConfirmarActivar`, `ofmConfirmarCampana`, `ofmConfirmarSacar`) | `GET /ml-ofertas/item/{id}/promociones|costo-envio|buscar`, `POST .../activar|activar-campana|sacar` (registran en "Historial Ofertas ML" con operador) |
| Aplicar precio en ML (Motor de Precios) | Motor de Precios (`ayalaCoreAbrirOferta`) | `POST /ayala-core/item/{id}/aplicar-precio` |
| Margen según cuota | Ofertas (`ofmMargenAt(…, cuotas)`), Competidores (`compToggleCuotas`), motor `precio_a_margen(plan=…)` | — |

### Hallazgos que condicionan el diseño
1. **Hay tres tablas de cuotas distintas.** Ofertas usa 3/6/9/12 = 8,9 / 13,4 / 17,8 / 21,6 % (igual a `pricing_cuotas` del motor); Competidores usa recargo × y % propios (1,15 y 4,08 % · 1,20 y 9,48 % · 1,25 y 15,12 % · 1,35 y 18,24 %). Son modelos distintos y dan márgenes distintos para la misma cuota.
   "Margen según la cuota" en la pantalla nueva necesita UNA tabla: propongo la del motor (como se hizo con el costo fijo), publicada por un `GET /rentabilidad/pricing/ml-cuotas`. **Hay que decidir cuál es la correcta** (¿el recargo de Competidores era un modelo intencional de cómo publican los rivales en cuotas?).
2. **Ofertas ML calcula envío con tramos propios** (0 / 7.000 / 7.470 o el real de la publicación), no con los $8.500 desde $33.000 de CRITERIOS_MARGEN §6. No lo toco sin tu OK; lo dejo anotado.
3. **Las acciones de escritura son por publicación (MLA + cuenta IT/MT), no por SKU.** La pantalla de competencia trabaja por SKU: hace falta resolver SKU → nuestras publicaciones. Opciones: el buscador por MLA que ya existe (`/ml-ofertas/item/{id}/buscar`), el mapa Base MLA / publicaciones de Ayala Core, o buscar por SKU en nuestra cuenta con la API de ML (nuestras publicaciones sí se pueden leer; **no verificado**).
4. **El panel "Gestionar" de Ofertas usa ids de elementos `ofm-*` por MLA y estado global (`ofmFilaPorId`, `OFM`).** Montarlo dentro de la pantalla nueva mientras la de Ofertas también existe en la página duplicaría ids. Para reusarlo sin copiarlo hay que parametrizar el contenedor en esas funciones (con valor por defecto = comportamiento actual) — es un cambio chico en código que usa Natalia, con prueba de regresión; o, alternativa sin tocarlo, mover el panel de lugar en el DOM al abrirlo desde competencia.
5. **Precio de sistema vs. planilla PM:** "Verificar Ecom" compara Ecom contra la planilla PM. Si se cambia el precio en Ecom desde Competencia, queda distinto de la PM hasta que el PM la actualice; la pantalla lo va a avisar.

### Cómo quedaría en la pantalla
Al abrir un SKU (clic en la fila) se despliega un panel **"Jugar mi precio"**: campo con nuestro precio (arranca en el de PM) y atajos (igualar al Barato, 1 % bajo el Rey, volver a PM); margen en vivo contra los criterios (sin IVA, 15,5 %, costo fijo corregido, IIBB, cheque, envío), margen por cuota (contado / 3 / 6 / 9 / 12) y la diferencia contra Rey / Media / Barato al lado. Debajo, los botones de acción, siempre con confirmación y operador, y con aviso (no bloqueo) si el margen queda bajo el umbral (CRITERIOS §8):
**[Aplicar precio de sistema (Ecom)]** y **[Oferta ML…]** (abre el panel de Gestionar con el precio ya cargado).

### Sub-etapas (cada una para revisar)
- **B0 (base, sin pantalla):** `GET /rentabilidad/pricing/ml-cuotas` + que Competidores/Ofertas la lean (según tu decisión del punto 1) + prueba de paridad ampliada + resolver SKU → publicaciones.
- **B1 Simulador (sin escribir nada):** panel "Jugar mi precio" con margen por cuota y comparación contra los rivales.
- **B2 Precio de sistema:** botón que reusa `compModEcom` → `/ecom/update-price`, con confirmación y registro.
- **B3 Ofertas:** panel de Gestionar dentro del SKU (activar / campaña / sacar), con la parametrización del contenedor y regresión sobre la pantalla de Ofertas.
Orden sugerido: A (costo cacheado) → B0 → B1 → B2 → B3.
