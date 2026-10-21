"""Idempotencia: correr el cierre dos veces deja la base y los reportes iguales."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from _datos import escribir_fuente

from cierre.pipeline import ejecutar

TABLAS = ["fact_ventas", "fact_meta_ejecutivo", "etl_rechazos", "dim_fecha", "dim_ejecutivo",
          "dim_sucursal", "dim_producto", "dim_segmento"]


def _foto(db: Path) -> dict:
    """Conteos por tabla, claves sustitutas y suma de montos: si algo se duplica, cambia."""
    with closing(sqlite3.connect(db)) as conn:
        foto = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLAS}
        foto["monto"] = conn.execute("SELECT SUM(monto_clp) FROM fact_ventas").fetchone()[0]
        foto["claves_ejecutivo"] = conn.execute(
            "SELECT group_concat(id_ejecutivo || ':' || ejecutivo_key) FROM dim_ejecutivo").fetchone()[0]
        foto["cargas"] = conn.execute("SELECT COUNT(*) FROM etl_cargas").fetchone()[0]
    return foto


class TestIdempotencia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.fuente = escribir_fuente(self.base / "fuente")
        self.db = self.base / "cierre.sqlite"
        self.salida = self.base / "output"

    def tearDown(self):
        self._tmp.cleanup()

    def _correr(self, **kw):
        return ejecutar("2026-09", self.fuente, self.db, self.salida, **kw)

    def test_dos_corridas_no_duplican(self):
        m1 = self._correr()
        f1 = _foto(self.db)
        m2 = self._correr()
        f2 = _foto(self.db)
        self.assertEqual(f1["fact_ventas"], 6)        # 2 de agosto + 4 de septiembre
        self.assertEqual(f1["etl_rechazos"], 1)
        # El log de cargas sí crece (es auditoría de corridas); los datos no.
        self.assertEqual(f2.pop("cargas"), 2 * f1.pop("cargas"))
        self.assertEqual(f1, f2)
        self.assertEqual(m1["cargas"][-1]["filas_cargadas"], m2["cargas"][-1]["filas_cargadas"])

    def test_reportes_identicos_entre_corridas(self):
        self._correr()
        primera = {p: p.read_bytes() for p in (self.salida / "por_segmento").rglob("*") if p.is_file()}
        self._correr()
        segunda = {p: p.read_bytes() for p in (self.salida / "por_segmento").rglob("*") if p.is_file()}
        self.assertEqual(primera, segunda)

    def test_dry_run_por_defecto_no_arma_mensajes(self):
        m = self._correr()
        self.assertTrue(m["dry_run"])
        self.assertEqual(m["reportes_por_segmento"], 2)
        self.assertFalse((self.salida / "por_segmento" / "bandeja_salida").exists())
        manifiesto = json.loads((self.salida / "por_segmento" / "envios_2026-09.json").read_text(encoding="utf-8"))
        self.assertEqual({e["estado"] for e in manifiesto["envios"]}, {"simulado"})
        self.assertEqual(manifiesto["fecha_programada"], "2026-10-01")  # día hábil siguiente al cierre

    def test_no_dry_run_arma_eml_sin_enviar(self):
        self._correr(dry_run=False)
        emls = sorted((self.salida / "por_segmento" / "bandeja_salida").glob("*.eml"))
        self.assertEqual([p.name for p in emls], ["cierre_2026-09_personas.eml", "cierre_2026-09_pyme.eml"])
        self.assertIn(b"To: pyme@empresa.example", emls[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
