# sales-close-automation

Automatización del **cierre comercial mensual**: extracción desde los sistemas fuente, **validación contra
reglas de negocio declaradas**, carga a un **modelo dimensional** y **reportes por segmento** listos para
enviar. Es una recreación, con datos 100 % sintéticos, de un proceso que diseñé y llevé a producción en una
empresa de servicios financieros.

> Este repositorio no contiene código, datos ni nombres de ningún cliente. Las sucursales son ciudades
> genéricas; los ejecutivos, clientes, productos, tarifas y montos son inventados.

## El problema

Cada cierre de mes, analistas senior juntaban a mano las colocaciones de varios sistemas, corregían
duplicados y montos mal informados, cruzaban contra metas y tarifas, y armaban un reporte distinto para cada
segmento de clientes. El trabajo era repetitivo, dependía de pocas personas y los reportes llegaban al
**quinto día hábil**: tarde para corregir el rumbo del mes siguiente.

Hacía falta que el cierre fuera **repetible** (mismas reglas cada mes), **auditable** (cada fila descartada
con su motivo) e **idempotente** (volver a correrlo después de corregir un archivo no duplica nada).

## La solución

```text
CSV de sistemas fuente ──► extracción ──► validación ──────────────► carga idempotente ──► KPIs ──► reportes
(colocaciones, metas,                     reglas_negocio.json         star schema SQLite            por segmento
 maestros, tarifario)                         │                      (fact_ventas + 5 dims)         HTML + CSV
                                              ▼                                                         │
                                        etl_rechazos                                                    ▼
                                  (línea, regla y motivo)                          envío simulado (--dry-run):
                                                                                   manifiesto y .eml, sin red
```

- **Reglas fuera del código** (`reglas/reglas_negocio.json`): campos obligatorios, operación única, monto
  positivo, fecha dentro del período, ejecutivo/sucursal/segmento existentes, producto con tarifa vigente y
  canal válido. El área comercial puede leerlas y cambiar parámetros sin tocar Python.
- **Validación auditable** (`validacion.py`): cada regla se evalúa por separado y se registran todos los
  motivos de una fila, con su línea en el archivo fuente. Nada se corrige en silencio.
- **Modelo dimensional** (`sql/ddl_modelo_dimensional.sql`): `fact_ventas` (grano: operación) con
  `dim_fecha`, `dim_ejecutivo`, `dim_sucursal`, `dim_producto` y `dim_segmento`, más `fact_meta_ejecutivo`
  para el cumplimiento y tablas de control (`etl_rechazos`, `etl_cargas`).
- **Idempotencia** (`carga.py`): dimensiones por UPSERT sobre clave natural (las claves sustitutas no
  cambian) y hechos, metas y rechazos del período reemplazados en una sola transacción.
- **KPIs de cierre** (`kpis.py`): cumplimiento de meta por ejecutivo y sucursal, mix de productos y
  variación vs mes anterior por segmento, sucursal o producto. Sin denominador no se informa 0 % ni infinito.
- **Reportes por segmento** (`reportes.py`, `envio.py`): HTML autocontenido para el cuerpo del correo y CSV
  para Excel, un manifiesto con destinatarios y la fecha programada (día hábil siguiente al cierre). Por
  defecto es `--dry-run`; **nunca se envía un correo**. Solo biblioteca estándar.

## Resultados medidos

Datos sintéticos: `python data/generate_synthetic.py` (semilla 42): 8 sucursales, 40 ejecutivos, 8 productos
con tarifa más uno sin tarifa vigente, 4 segmentos, agosto y septiembre de 2026. El cierre de septiembre
recarga también agosto para calcular la variación.

| Métrica (cierre de septiembre 2026) | Valor |
|---|---:|
| Filas leídas / cargadas / rechazadas | 6.087 / 5.829 / 258 (4,2 %) |
| Errores inyectados detectados | **258 de 258**, sin rechazos indebidos |
| Tiempo del pipeline completo (2 meses, 12.004 filas, KPIs y reportes) | 0,11–0,12 s |
| Mismo pipeline a 10× volumen (117.061 filas) | 1,12–1,14 s |
| Reportes por segmento | 4 (HTML + CSV) + resumen general y manifiesto: 11 archivos |
| Segunda corrida sobre la misma base | 11.496 filas en `fact_ventas`, igual que la primera |

Rechazos por regla en septiembre:

| Regla | Error inyectado | Rechazos |
|---|---|---:|
| `R02_operacion_unica` | operación extraída dos veces | 90 |
| `R03_monto_positivo` | reversa informada como monto negativo | 48 |
| `R04_fecha_en_periodo` | operación del mes anterior o siguiente | 36 |
| `R08_producto_con_tarifa` | producto sin tarifa de comisión vigente | 36 |
| `R05_ejecutivo_existe` | código de ejecutivo inexistente | 30 |
| `R01_campos_obligatorios` | segmento vacío | 18 |

Tiempos medidos con `time.perf_counter` en 5 corridas desde una base vacía (Apple M4 Pro, Python 3.14). La
escala 10× se genera con `--ejecutivos-por-sucursal 50`. El cuello de botella de un cierre nunca fue el
cómputo: era la consolidación manual y las idas y vueltas para corregir datos.

Lo que muestra el resumen del demo: $114.265.800.000 colocados (+3,5 % vs agosto), cumplimiento global de
93,6 %, 13 de 40 ejecutivos sobre la meta y sucursales entre 81,2 % y 101,5 %.

## Cómo usarlo

```bash
python data/generate_synthetic.py --periodos 2026-08 2026-09 --seed 42
PYTHONPATH=src python -m cierre --periodo 2026-09                 # dry-run (por defecto)
PYTHONPATH=src python -m cierre --periodo 2026-09 --no-dry-run    # arma los .eml, tampoco envía

python -m unittest discover -s tests
```

Salidas en `output/`:

- `cierre.sqlite`: el modelo dimensional, consultable con cualquier cliente SQLite.
- `por_segmento/<segmento>/cierre_2026-09_<segmento>.html` y `.csv`: el reporte de cada segmento.
- `por_segmento/envios_2026-09.json`: destinatarios, asunto, adjuntos, fecha programada y estado.
- `resumen_cierre_2026-09.html`, `cumplimiento_ejecutivos_2026-09.csv` y `metricas_2026-09.json`.

Los rechazos quedan en la tabla `etl_rechazos`:

```sql
SELECT regla, linea, id_operacion, motivo FROM etl_rechazos WHERE periodo = '2026-09' LIMIT 5;
```

Los tests cubren cada tipo de regla, la detección de todos los errores inyectados, la idempotencia (base y
reportes idénticos entre corridas), el `--dry-run` y los KPIs contra un caso pequeño calculado a mano.

## Cómo se conecta Power BI al modelo

El DDL es el mismo star schema que en producción vivía en SQL Server (aquí en dialecto SQLite).

```text
dim_fecha ─────┐
dim_ejecutivo ─┼──1:*──► fact_ventas          dim_ejecutivo ──1:*──► fact_meta_ejecutivo
dim_sucursal ──┤                               (meta mensual; se filtra por período con TREATAS)
dim_producto ──┤
dim_segmento ──┘
```

1. **Conexión**: conector SQL Server en modo Importación, con actualización programada después de la carga.
   DirectQuery solo si el negocio necesita ver el cierre mientras se carga.
2. **Modelo**: relaciones uno a varios desde cada dimensión a `fact_ventas`, filtro en una sola dirección y
   `dim_fecha` marcada como tabla de fechas. Las tablas `etl_*` van a una página de calidad de datos, fuera
   del modelo de negocio.
3. **Metas**: `fact_meta_ejecutivo` tiene grano mensual. Se relaciona con `dim_ejecutivo` y se filtra por
   período con `TREATAS`. El cumplimiento por sucursal usa la sucursal de dotación del ejecutivo, para que
   ventas y metas compartan el mismo eje.
4. **Seguridad por segmento**: un rol RLS sobre `dim_segmento` para que cada jefatura vea solo lo suyo.

Medidas DAX de ejemplo:

```dax
Ventas = SUM ( fact_ventas[monto_clp] )

Meta =
CALCULATE (
    SUM ( fact_meta_ejecutivo[meta_clp] ),
    TREATAS ( VALUES ( dim_fecha[periodo] ), fact_meta_ejecutivo[periodo] )
)

Cumplimiento % = DIVIDE ( [Ventas], [Meta] )

Ventas mes anterior = CALCULATE ( [Ventas], DATEADD ( dim_fecha[fecha], -1, MONTH ) )

Var % vs mes anterior = DIVIDE ( [Ventas] - [Ventas mes anterior], [Ventas mes anterior] )

Mix % = DIVIDE ( [Ventas], CALCULATE ( [Ventas], ALL ( dim_producto ) ) )
```

`DIVIDE` devuelve vacío cuando no hay meta o mes anterior: el mismo criterio que `kpis.py`, donde la
variación sin base queda indefinida y no en 0 %.

## Qué llevé a producción en el caso real

- Extracción y validación en Python contra reglas de negocio acordadas con el área comercial; los rechazos
  volvían con su motivo a los dueños de cada sistema.
- Modelo dimensional en SQL Server con Power BI encima: cumplimiento de meta, variación y mix.
- Envío automático de cada reporte a su segmento con Power Automate.
- Resultado: los reportes que se consolidaban a mano y llegaban el quinto día hábil pasaron a llegar **el día
  hábil siguiente al cierre**.

## Limitaciones del demo

- El envío es simulado: hay manifiesto y `.eml`, pero ninguna conexión SMTP ni Power Automate.
- `dim_ejecutivo` es SCD tipo 1: si un ejecutivo cambia de sucursal, el histórico se reasigna.
- Si la primera aparición de una operación duplicada es inválida, la copia también se rechaza (se conserva
  la primera aparición, aunque sea inválida). Es un criterio conservador.
- Los feriados son una lista de referencia en `calendario.py`; en producción vendrían de una tabla
  corporativa.
- El DDL está en dialecto SQLite. Las rutas a `sql/` y `reglas/` suponen que se ejecuta desde el repositorio
  (o con `pip install -e .`).

## Stack

Python 3.10+ (solo biblioteca estándar) · SQLite · SQL (star schema) · Power BI / DAX (diseño) · unittest

---

**Nicolás González Rojas** · Head of Data & BI · [LinkedIn](https://www.linkedin.com/in/nicolas-gonzalez-rojas)
