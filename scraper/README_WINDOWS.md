# Scraper de competencia — instalación en Windows

Corre en **tu PC** (la misma donde hoy corrés `ml_vendedor.py`: ya tiene Python y Chrome), programado a las **17:30** con
Tareas de Windows. Lee la planilla de Maca, scrapea los perfiles de tienda y las publicaciones puntuales y escribe las
lecturas en `Historial_Precios` (+ eventos en `Eventos_Competencia`).

## 1. Instalar (una sola vez)
1. Bajá el repo como ZIP desde GitHub (rama `claude/eager-sagan-3i5ezo` mientras no esté mergeado; después `main`) y
   descomprimilo en `C:\ayala-erp\`. Tiene que quedar `C:\ayala-erp\scraper\scraper.py`.
2. Abrí `cmd` y corré:
   ```
   cd C:\ayala-erp\scraper
   pip install -r requirements.txt
   ```
3. Copiá el JSON de la cuenta de servicio (el mismo que usa `ml_vendedor.py`) a `C:\ayala-erp\scraper\credentials.json`.
   **Nunca va a GitHub** (está en `.gitignore`). La cuenta es `ml-tracker@reporte-de-ventas-leandro.iam.gserviceaccount.com`:
   tiene que ser **lector** de la planilla de Maca (ya está compartida) y **editora** del Sheet del ERP (ya lo es).

## 2. Login de Mercado Libre (una sola vez)
```
python scraper.py --configurar-login
```
Se abre un Chrome **propio del scraper** (no tu Chrome de todos los días): iniciá sesión en Mercado Libre, abrí cualquier
publicación para confirmar que ves precios y volvé a la consola a apretar ENTER. **No se guarda usuario ni contraseña**: queda
solo la sesión en la carpeta `scraper\perfil_chrome\` (también fuera de git). Si ML vuelve a pedir login o verificación,
repetí este paso.

## 3. Modo prueba (antes de la primera corrida real)
```
python scraper.py --probar 20
```
Lee ~20 links reales (4 tiendas y publicaciones de cada tipo: catálogo con `wid`, catálogo sin `wid` y directas) y **no
escribe nada**. Al final imprime un resumen y guarda `scraper\logs\prueba_scraper_AAAAMMDD_HHMM.json`: pasame ese archivo
(o pegá el resumen). Con eso se confirma qué muestra ML en cada tipo de link antes de tocar el histórico.

### Cómo se lee un link de catálogo (`/p/…?wid=…`)
Al abrir un `/p/`, Mercado Libre muestra a la **oferta ganadora**, no a la del `wid` que carga Maca. Por eso, para el competidor:
1. se busca en esa misma página la **tarjeta de la oferta del `wid`** (precio y vendedor);
2. si no está a la vista, se hace clic en **"Más opciones de compra"** y se vuelve a buscar;
3. si configuraste la **vía API** (abajo), se le pregunta al backend por las ofertas del producto;
4. como último recurso se abre la página del ítem `/MLA-<wid>`, que **solo existe si la oferta no es una publicación de catálogo**
   (si es de catálogo, ML la redirige al `/p/`: ahí no hay link directo posible).

Siempre se guarda además el **precio de la ganadora** en `Historial_Precios` (`Precio_Ganador` y `Vendedor_Ganador`), junto al del
competidor. Los eventos de cambio de precio miran **solo** el precio del competidor. Si no se pudo leer la oferta del competidor
no se guarda fila (aunque se haya visto a la ganadora): el histórico solo tiene lecturas del competidor que seguimos.

**Vía API (opcional):** si definís en Windows `setx ERP_BACKEND_URL https://TU-BACKEND` y `setx ERP_API_KEY TU-CLAVE` (y abrís una consola
nueva), el scraper puede traer el precio de la oferta del `wid` y el de la ganadora sin abrir la página. Si ML responde 403 se apaga sola.

## 4. Corrida real (primera vez)
Actualizá la carpeta con el ZIP más reciente de la rama y, desde `C:\ayala-erp\scraper`:

1. **Ensayo sin escribir** (lee todo, no toca ningún Sheet; tarda unos minutos):
   ```
   python scraper.py --sin-escribir --sin-descubrimiento
   ```
   Mirá el resumen del final. Con la planilla de hoy tiene que decir, más o menos: 4 entidades nuevas (WTP WOW TOTAL PRINT, SUDINEROSEGURO,
   MORSHOP, GEOTEK), ~103 referencias nuevas, 3 `Link_ML` a completar, ~90 publicaciones leídas, 0 con error, y la lista "Para completar en la
   planilla" (links de catálogo sin `wid`, que NO se leen). Si dice `CORRIDA CORTADA` repetí `--configurar-login`.
2. **Corrida real:**
   ```
   python scraper.py --sin-descubrimiento
   ```
   (`--sin-descubrimiento` la primera vez: así no se vuelcan de golpe a `Discovery_Sugerencias` todas las publicaciones de las tiendas que no
   son referencias, que pueden ser miles. Las siguientes corridas, sin esa opción, las van registrando.)
3. **Qué verificar en los Sheets** (Sheet del ERP):
   - `Entidades`: +4 filas (las de arriba) y `Link_ML` completado en TECNOVIBEARG, AMERICANCOMPUTERS y ELEPHANT CARTDRIGE. Global no se toca.
   - `Referencias_Mercado`: ~+103 filas con `Origen = Planilla Maca B-SKU` y `Rol_Competidor` (Rey/Media/Barato) completo.
   - `Historial_Precios`: ahora tiene 15 columnas (se agregaron `Precio_Ganador` y `Vendedor_Ganador` al final; las 13 de antes no se movieron).
     Filas nuevas con `Fuente` = `Scraper perfil` o `Scraper publicación`, **todas con `Precio`**. En los links de catálogo, `Precio_Ganador` junto al `Precio`.
     Ninguna fila con `Entidad` GLOBAL ELECTRONICS.
   - **Idempotencia:** corré lo mismo de nuevo ese día (`python scraper.py --sin-descubrimiento`): la cantidad de filas de `Historial_Precios`
     **no** tiene que crecer (la lectura nueva reemplaza la del día).
   - `Eventos_Competencia`: la primera vez puede haber `Bajo`/`Subio` en referencias que ya tenían historial (migradas); no tiene que haber
     decenas de `Publicacion_caida` ni `Vendedor_sin_resultados` (si los hay, algo falló al leer: avisame antes de la tarea programada).
   - **3 chequeos a ojo:** abrí 3 publicaciones en ML y compará el precio con la fila (una de perfil, una directa y una de catálogo con `wid`).
   - Las pestañas viejas (`V - *`, `Monitor_Lecturas`, `Historial Competidores`) quedan intactas.
   - En `scraper\logs\` quedan `corrida_*.log` y `corrida_*.json` con el resumen.
4. Recién cuando esto cierre, programá la tarea (paso siguiente). Al otro día revisá el log de la primera corrida automática.

### Filas sin competidor cargado
Las celdas de competidor con `-` o vacías (hoy 1.387 SKU sin competidor) no son competidores todavía: se saltean sin ruido y el resumen solo las
cuenta. Un link de catálogo (`/p/` o `/up/`) **sin `?wid=`** no se lee (no hay forma de saber cuál es la oferta del competidor): sale en
"Para completar en la planilla" con el SKU y el rol, para que Maca agregue el `wid`.

## 5. Programar la tarea a las 17:30
En `cmd` (como tu usuario):
```
schtasks /Create /TN "Ayala Scraper Competencia" /TR "C:\ayala-erp\scraper\ejecutar_scraper.bat" /SC DAILY /ST 17:30 /RL LIMITED /F
```
Requisitos: a las 17:30 la **PC encendida y tu usuario con la sesión iniciada** (la tarea corre "solo cuando el usuario haya
iniciado sesión", necesario para que Chrome tenga el perfil). En el Programador de tareas podés tildar "Ejecutar lo antes
posible si se perdió una ejecución programada". Probala con botón derecho → *Ejecutar*.

## 6. Uso diario
| Quiero… | Comando |
|---|---|
| Corrida diaria, todos los vendedores | `python scraper.py` (o `ejecutar_scraper.bat`) |
| Actualizar UN vendedor ahora | `python scraper.py --vendedor tecnovibe` |
| Solo tiendas completas / solo links puntuales | `--solo perfiles` / `--solo publicaciones` |
| Ver qué haría sin escribir | `--sin-escribir` |
| No registrar publicaciones nuevas de las tiendas | `--sin-descubrimiento` |

Si corrés el mismo día dos veces, la lectura nueva **reemplaza** la del día (no duplica filas).
Códigos de salida: `0` ok · `1` error · `2` ML pidió login/verificación (corrida cortada: repetí el paso 2).
Los logs quedan en `scraper\logs\` (`corrida_*.log` y `corrida_*.json` con el resumen).

## Qué hace y qué no
- **Planilla de Maca** (A-CATEGORIAS y B-SKU-COMPETENCIA, encabezados en la fila 3): la define Maca. El scraper no clasifica nada;
  cada corrida vuelve a leerla, así que los links nuevos que Maca cargue se toman solos al día siguiente.
- **Referencias_Mercado**: crea una referencia por (SKU, publicación) de B-SKU, con `Rol_Competidor` (Rey/Media/Barato). No pisa datos
  existentes: solo completa vacíos. Un link que ya existe con otro SKU se informa, no se pisa.
- **Entidades**: las tiendas de A se vinculan por alias a las existentes (tecnovibe→TECNOVIBEARG, american-computers→AMERICANCOMPUTERS,
  elephant-cartridge→ELEPHANT CARTDRIGE); las demás se crean como Competencia.
- **Global Electronics** nunca se scrapea (`config.EXCLUIR_ENTIDADES`).
- **Eventos**: `Bajo`/`Subio` (cualquier cambio vs. la última lectura), `Publicacion_caida` (solo si la página cargó y lo dice; un timeout
  no cuenta), `Reaparecio`, `Vendedor_sin_resultados`. Cada uno una sola vez por día.
- **Stock bajo (< 5): DESACTIVADO.** La columna de stock de B-SKU todavía no tiene la fórmula real. Cuando Maca la cargue, poné
  `STOCK_ALERTAS_ACTIVAS = True` en `config.py` (y solo se emite para SKU con competidores cargados).
- **Lo que una tienda muestra y no es referencia** va a `Discovery_Sugerencias` (sin SKU sugerido) para que Maca decida; no se crea
  ninguna referencia sola.
- Un link `/p/` de catálogo **sin** `wid` queda "Sin lectura" salvo que se pueda atribuir al vendedor esperado: nunca se guarda el precio
  de la oferta ganadora como si fuera de ese vendedor.
