"""Distribución de reportes por segmento (simulada).

Este repositorio **nunca envía correos**. En el caso real el envío lo hacía un flujo de
Power Automate que tomaba los archivos generados y los mandaba a la lista de cada segmento.
Aquí se reproduce el punto de entrega:

- `--dry-run` (por defecto): se escribe un manifiesto `envios_AAAA-MM.json` con destinatarios,
  asunto, adjuntos y fecha programada; estado `simulado`.
- `--no-dry-run`: además se arma cada mensaje como `.eml` (MIME estándar con HTML y adjuntos)
  en `bandeja_salida/`; estado `listo_para_enviar`. Es lo que recogería un relay SMTP o un
  flujo de Power Automate. Tampoco se conecta a ningún servidor.
"""

from __future__ import annotations

import json
from email.message import EmailMessage
from pathlib import Path

from .calendario import primer_dia_habil_siguiente
from .reportes import Reporte, nombre_periodo, slug

REMITENTE = "cierre-comercial@empresa.example"  # dominio reservado (RFC 2606): no existe


def _armar_eml(reporte: Reporte, asunto: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = REMITENTE
    msg["To"] = reporte.destinatarios
    msg["Subject"] = asunto
    msg.set_content(f"Adjunto el {asunto.lower()}. Este mensaje se generó automáticamente.")
    msg.add_alternative(reporte.html.read_text(encoding="utf-8"), subtype="html")
    msg.add_attachment(reporte.csv.read_bytes(), maintype="text", subtype="csv", filename=reporte.csv.name)
    return msg


def preparar_envios(reportes: list[Reporte], periodo: str, destino: Path, dry_run: bool = True) -> dict:
    destino = Path(destino)
    fecha_envio = primer_dia_habil_siguiente(periodo).isoformat()
    envios = []
    for r in reportes:
        asunto = f"Cierre comercial {nombre_periodo(periodo)} - Segmento {r.segmento}"
        envio = {
            "segmento": r.segmento,
            "para": r.destinatarios,
            "asunto": asunto,
            "adjuntos": [str(r.html.relative_to(destino)), str(r.csv.relative_to(destino))],
            "fecha_programada": fecha_envio,
            "estado": "simulado" if dry_run else "listo_para_enviar",
        }
        if not dry_run:
            bandeja = destino / "bandeja_salida"
            bandeja.mkdir(parents=True, exist_ok=True)
            ruta_eml = bandeja / f"cierre_{periodo}_{slug(r.segmento)}.eml"
            ruta_eml.write_bytes(bytes(_armar_eml(r, asunto)))
            envio["mensaje"] = str(ruta_eml.relative_to(destino))
        envios.append(envio)
    manifiesto = {"periodo": periodo, "dry_run": dry_run, "remitente": REMITENTE,
                  "fecha_programada": fecha_envio, "envios": envios}
    (destino / f"envios_{periodo}.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    return manifiesto
