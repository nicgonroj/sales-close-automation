"""Reglas de validación: cada tipo de regla detecta su error y deja pasar lo correcto."""

from __future__ import annotations

import json
import unittest

from _datos import MAESTROS, RAIZ, op

from cierre.extraccion import extraer
from cierre.validacion import cargar_reglas, validar

REGLAS = cargar_reglas(RAIZ / "reglas" / "reglas_negocio.json")


def _validar(*filas):
    numeradas = [dict(f, _linea=i) for i, f in enumerate(filas, start=2)]
    return validar(numeradas, MAESTROS, REGLAS, "2026-09")


def _reglas(res):
    return sorted({r.regla for r in res.rechazos})


class TestReglas(unittest.TestCase):
    def test_fila_correcta_pasa(self):
        res = _validar(op("X1", "2026-09-15", "E1", "S1", "P1", "G1", 1000))
        self.assertEqual(len(res.validas), 1)
        self.assertEqual(res.rechazos, [])
        self.assertIsInstance(res.validas[0]["monto_clp"], int)

    def test_campo_obligatorio_vacio(self):
        res = _validar(op("X1", "2026-09-15", "E1", "S1", "P1", "", 1000))
        self.assertEqual(_reglas(res), ["R01_campos_obligatorios"])  # no se cuenta también como R07

    def test_duplicado_conserva_la_primera(self):
        fila = op("X1", "2026-09-15", "E1", "S1", "P1", "G1", 1000)
        res = _validar(fila, dict(fila))
        self.assertEqual(len(res.validas), 1)
        self.assertEqual(_reglas(res), ["R02_operacion_unica"])
        self.assertEqual(res.rechazos[0].linea, 3)
        self.assertIn("línea 2", res.rechazos[0].motivo)

    def test_monto_negativo_cero_y_no_numerico(self):
        res = _validar(op("X1", "2026-09-15", "E1", "S1", "P1", "G1", -500),
                       op("X2", "2026-09-15", "E1", "S1", "P1", "G1", 0),
                       op("X3", "2026-09-15", "E1", "S1", "P1", "G1", "12a"))
        self.assertEqual(res.filas_rechazadas, 3)
        self.assertEqual(res.rechazos_por_regla(), {"R03_monto_positivo": 3})

    def test_fecha_fuera_del_periodo_o_invalida(self):
        res = _validar(op("X1", "2026-08-31", "E1", "S1", "P1", "G1", 1),
                       op("X2", "2026-10-01", "E1", "S1", "P1", "G1", 1),
                       op("X3", "2026-09-31", "E1", "S1", "P1", "G1", 1))
        self.assertEqual(res.rechazos_por_regla(), {"R04_fecha_en_periodo": 3})

    def test_maestros_inexistentes(self):
        res = _validar(op("X1", "2026-09-15", "E9", "S1", "P1", "G1", 1),
                       op("X2", "2026-09-15", "E1", "S9", "P1", "G1", 1),
                       op("X3", "2026-09-15", "E1", "S1", "P1", "G9", 1))
        self.assertEqual(res.rechazos_por_regla(),
                         {"R05_ejecutivo_existe": 1, "R06_sucursal_existe": 1, "R07_segmento_existe": 1})

    def test_producto_sin_tarifa_o_inexistente(self):
        res = _validar(op("X1", "2026-09-15", "E1", "S1", "P3", "G1", 1),
                       op("X2", "2026-09-15", "E1", "S1", "P9", "G1", 1))
        self.assertEqual(res.rechazos_por_regla(), {"R08_producto_con_tarifa": 2})
        self.assertIn("sin tarifa", res.rechazos[0].motivo)
        self.assertIn("no existe", res.rechazos[1].motivo)

    def test_canal_fuera_de_dominio(self):
        res = _validar(op("X1", "2026-09-15", "E1", "S1", "P1", "G1", 1, canal="Fax"))
        self.assertEqual(_reglas(res), ["R09_canal_valido"])

    def test_registra_todos_los_motivos_de_una_fila(self):
        res = _validar(op("X1", "2026-07-01", "E9", "S1", "P3", "G1", -1))
        self.assertEqual(res.filas_rechazadas, 1)
        self.assertEqual(_reglas(res), ["R03_monto_positivo", "R04_fecha_en_periodo",
                                        "R05_ejecutivo_existe", "R08_producto_con_tarifa"])

    def test_tipo_de_regla_desconocido_falla_al_cargar(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "reglas.json"
            ruta.write_text(json.dumps({"reglas": [{"id": "RX", "tipo": "magia"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                cargar_reglas(ruta)


class TestDatosSinteticos(unittest.TestCase):
    """La validación encuentra exactamente los errores que inyectó el generador."""

    def test_detecta_todos_los_errores_inyectados(self):
        fuente = RAIZ / "data" / "fuente"
        verdad_path = fuente / "_errores_inyectados_2026-09.json"
        if not verdad_path.exists():
            self.skipTest("Primero: python data/generate_synthetic.py")
        verdad = json.loads(verdad_path.read_text(encoding="utf-8"))
        ext = extraer(fuente, "2026-09")
        res = validar(ext.ventas, ext.maestros, REGLAS, "2026-09")
        e = verdad["errores_inyectados"]
        self.assertEqual(res.rechazos_por_regla(), {
            "R01_campos_obligatorios": e["segmento_vacio"],
            "R02_operacion_unica": e["duplicado"],
            "R03_monto_positivo": e["monto_negativo"],
            "R04_fecha_en_periodo": e["fecha_fuera_periodo"],
            "R05_ejecutivo_existe": e["ejecutivo_inexistente"],
            "R08_producto_con_tarifa": e["producto_sin_tarifa"],
        })
        self.assertEqual(len(res.validas), verdad["filas_validas_esperadas"])


if __name__ == "__main__":
    unittest.main()
