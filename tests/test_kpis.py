"""KPIs sobre un caso pequeño calculado a mano (ver tests/_datos.py).

Septiembre válido: E1 = 600 + 300, E2 = 2.500, E3 = 400 → total 3.800 (B5 se rechaza).
Agosto: 2.000. Metas de septiembre: E1 1.000, E2 2.000, E3 1.000.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _datos import RAIZ, escribir_fuente

from cierre import kpis
from cierre.carga import conectar
from cierre.pipeline import procesar_periodo
from cierre.validacion import cargar_reglas


class TestKpis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        fuente = escribir_fuente(Path(cls.tmp.name) / "fuente")
        reglas = cargar_reglas(RAIZ / "reglas" / "reglas_negocio.json")
        cls.conn = conectar(":memory:")
        for periodo in ("2026-08", "2026-09"):
            procesar_periodo(cls.conn, fuente, periodo, reglas)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_resumen_y_variacion_total(self):
        r = kpis.resumen_periodo(self.conn, "2026-09")
        self.assertEqual(r["operaciones"], 4)
        self.assertEqual(r["monto_clp"], 3800)
        self.assertAlmostEqual(r["comision_clp"], 6 + 30 + 25 + 40)   # 600·1 % + 300·10 % + 2.500·1 % + 400·10 %
        self.assertAlmostEqual(r["ticket_medio_clp"], 950)
        self.assertAlmostEqual(r["var_vs_mes_anterior"], (3800 - 2000) / 2000)  # +90 %

    def test_cumplimiento_por_ejecutivo(self):
        c = {f["id_ejecutivo"]: f["cumplimiento"] for f in kpis.cumplimiento_ejecutivos(self.conn, "2026-09")}
        self.assertAlmostEqual(c["E1"], 0.90)
        self.assertAlmostEqual(c["E2"], 1.25)
        self.assertAlmostEqual(c["E3"], 0.40)

    def test_cumplimiento_por_sucursal_suma_metas_de_la_dotacion(self):
        c = {f["sucursal"]: f for f in kpis.cumplimiento_sucursales(self.conn, "2026-09")}
        self.assertEqual((c["Norte"]["monto_clp"], c["Norte"]["meta_clp"]), (3400, 3000))
        self.assertAlmostEqual(c["Norte"]["cumplimiento"], 3400 / 3000)
        self.assertAlmostEqual(c["Sur"]["cumplimiento"], 0.40)

    def test_mix_de_productos(self):
        mix = {f["id_producto"]: f["participacion"] for f in kpis.mix_productos(self.conn, "2026-09")}
        self.assertAlmostEqual(mix["P1"], 3100 / 3800)
        self.assertAlmostEqual(mix["P2"], 700 / 3800)
        self.assertAlmostEqual(sum(mix.values()), 1.0)

    def test_mix_dentro_de_un_segmento(self):
        mix = {f["id_producto"]: f["participacion"] for f in kpis.mix_productos(self.conn, "2026-09", "G2")}
        self.assertAlmostEqual(mix["P1"], 2500 / 2900)

    def test_variacion_por_segmento(self):
        v = {f["nombre"]: f["var_vs_mes_anterior"] for f in kpis.variacion_vs_anterior(self.conn, "2026-09", "segmento")}
        self.assertAlmostEqual(v["Personas"], (900 - 500) / 500)    # +80 %
        self.assertAlmostEqual(v["Pyme"], (2900 - 1500) / 1500)     # +93,3 %

    def test_sin_mes_anterior_no_inventa_variacion(self):
        v = {f["nombre"]: f for f in kpis.variacion_vs_anterior(self.conn, "2026-09", "sucursal", "G2")}
        # Norte no vendió Pyme en agosto: la variación queda indefinida, no en 0 % ni infinito.
        self.assertIsNone(v["Norte"]["var_vs_mes_anterior"])
        self.assertIsNone(kpis.resumen_periodo(self.conn, "2026-08")["var_vs_mes_anterior"])

    def test_rechazos_registrados_con_motivo(self):
        fila = self.conn.execute(
            "SELECT linea, id_operacion, regla, motivo FROM etl_rechazos WHERE periodo = '2026-09'").fetchall()
        self.assertEqual(len(fila), 1)
        self.assertEqual((fila[0]["linea"], fila[0]["id_operacion"], fila[0]["regla"]), (6, "B5", "R03_monto_positivo"))
        self.assertIn("-100", fila[0]["motivo"])


if __name__ == "__main__":
    unittest.main()
