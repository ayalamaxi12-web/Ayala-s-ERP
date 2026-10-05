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

## 4. Primera corrida
```
python scraper.py --sin-escribir     # corre completo pero NO toca ningún Sheet: mirá el resumen
python scraper.py                    # corrida real
```

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
