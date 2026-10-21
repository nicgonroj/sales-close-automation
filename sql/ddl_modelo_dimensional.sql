-- Modelo dimensional del cierre comercial mensual (star schema).
-- Dialecto: SQLite. La versión productiva corría en SQL Server; las diferencias
-- se limitan a tipos (INTEGER/TEXT/REAL ↔ INT/NVARCHAR/DECIMAL) y a IDENTITY.
-- Todas las sentencias son idempotentes: se pueden ejecutar en cada corrida.

PRAGMA foreign_keys = ON;

-- ───────────── Dimensiones ─────────────

CREATE TABLE IF NOT EXISTS dim_fecha (
    fecha_key     INTEGER PRIMARY KEY,          -- AAAAMMDD
    fecha         TEXT    NOT NULL UNIQUE,      -- ISO AAAA-MM-DD
    anio          INTEGER NOT NULL,
    mes           INTEGER NOT NULL,
    dia           INTEGER NOT NULL,
    periodo       TEXT    NOT NULL,             -- AAAA-MM
    dia_semana    INTEGER NOT NULL,             -- 1 = lunes … 7 = domingo
    es_habil      INTEGER NOT NULL CHECK (es_habil IN (0, 1))
);

CREATE TABLE IF NOT EXISTS dim_sucursal (
    sucursal_key  INTEGER PRIMARY KEY,
    id_sucursal   TEXT    NOT NULL UNIQUE,      -- clave natural del sistema fuente
    nombre        TEXT    NOT NULL,
    region        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_ejecutivo (
    ejecutivo_key INTEGER PRIMARY KEY,
    id_ejecutivo  TEXT    NOT NULL UNIQUE,
    nombre        TEXT    NOT NULL,
    id_sucursal   TEXT    NOT NULL,             -- sucursal de dotación (atributo, SCD tipo 1)
    sucursal_key  INTEGER REFERENCES dim_sucursal (sucursal_key)
);

CREATE TABLE IF NOT EXISTS dim_producto (
    producto_key    INTEGER PRIMARY KEY,
    id_producto     TEXT    NOT NULL UNIQUE,
    nombre          TEXT    NOT NULL,
    familia         TEXT    NOT NULL,
    tarifa_comision REAL                         -- NULL = sin tarifa vigente
);

CREATE TABLE IF NOT EXISTS dim_segmento (
    segmento_key      INTEGER PRIMARY KEY,
    id_segmento       TEXT    NOT NULL UNIQUE,
    nombre            TEXT    NOT NULL,
    lista_distribucion TEXT   NOT NULL          -- destinatarios del reporte del segmento
);

-- ───────────── Hechos ─────────────

-- Grano: una operación (colocación o venta) aprobada en el período.
CREATE TABLE IF NOT EXISTS fact_ventas (
    id_operacion  TEXT    PRIMARY KEY,          -- clave natural: garantiza idempotencia
    periodo       TEXT    NOT NULL,
    fecha_key     INTEGER NOT NULL REFERENCES dim_fecha (fecha_key),
    ejecutivo_key INTEGER NOT NULL REFERENCES dim_ejecutivo (ejecutivo_key),
    sucursal_key  INTEGER NOT NULL REFERENCES dim_sucursal (sucursal_key),
    producto_key  INTEGER NOT NULL REFERENCES dim_producto (producto_key),
    segmento_key  INTEGER NOT NULL REFERENCES dim_segmento (segmento_key),
    canal         TEXT    NOT NULL,
    monto_clp     INTEGER NOT NULL CHECK (monto_clp > 0),
    comision_clp  REAL    NOT NULL,
    id_carga      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fact_ventas_periodo ON fact_ventas (periodo);

-- Grano: meta mensual de un ejecutivo. La meta de la sucursal es la suma de sus ejecutivos.
CREATE TABLE IF NOT EXISTS fact_meta_ejecutivo (
    periodo       TEXT    NOT NULL,
    ejecutivo_key INTEGER NOT NULL REFERENCES dim_ejecutivo (ejecutivo_key),
    meta_clp      INTEGER NOT NULL CHECK (meta_clp > 0),
    PRIMARY KEY (periodo, ejecutivo_key)
);

-- ───────────── Control del proceso (no forma parte del star schema) ─────────────

CREATE TABLE IF NOT EXISTS etl_rechazos (
    periodo       TEXT    NOT NULL,
    archivo       TEXT    NOT NULL,
    linea         INTEGER NOT NULL,             -- línea del CSV fuente (1 = encabezado)
    id_operacion  TEXT,
    regla         TEXT    NOT NULL,
    motivo        TEXT    NOT NULL,
    id_carga      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_etl_rechazos_periodo ON etl_rechazos (periodo);

CREATE TABLE IF NOT EXISTS etl_cargas (
    id_carga         TEXT    PRIMARY KEY,
    periodo          TEXT    NOT NULL,
    archivo          TEXT    NOT NULL,
    ejecutado_en     TEXT    NOT NULL,
    filas_leidas     INTEGER NOT NULL,
    filas_cargadas   INTEGER NOT NULL,
    filas_rechazadas INTEGER NOT NULL
);
