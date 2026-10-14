"""Registro por tarea: herramientas, tokens, latencia y costo.

El precio por token todavía no lo confirma Platica (pregunta 8 del reto).
Hasta entonces el costo se marca como estimado y la tarifa sale de .env,
nunca queda escondida en el código de una corrida.
"""
import json
import os
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

# Tarifa provisional por millón de tokens. Sustituir cuando Platica la publique.
PRECIO_MILLON_ENTRADA = float(os.getenv("PRECIO_MILLON_ENTRADA", "0.60"))
PRECIO_MILLON_SALIDA = float(os.getenv("PRECIO_MILLON_SALIDA", "1.20"))


def registrar_uso(tarea_id, modelo, prompt_tokens, completion_tokens, latencia_segundos, traza=None):
    LOGS_DIR.mkdir(exist_ok=True)
    costo = (prompt_tokens / 1_000_000) * PRECIO_MILLON_ENTRADA + (
        completion_tokens / 1_000_000
    ) * PRECIO_MILLON_SALIDA
    registro = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "tarea_id": tarea_id,
        "modelo": modelo,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latencia_segundos": round(latencia_segundos, 2),
        "costo_estimado_usd": round(costo, 6),
        "tarifa": "provisional",
        "herramientas": [
            {"herramienta": paso["herramienta"], "argumentos": paso["argumentos"]}
            for paso in (traza or [])
        ],
        "resultado_herramientas": [paso["resultado"] for paso in (traza or [])],
    }
    with open(LOGS_DIR / "consumo.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
