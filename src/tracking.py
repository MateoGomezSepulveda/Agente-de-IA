"""Registro por tarea: herramientas, tokens, latencia, desglose y métricas FinOps.

El precio por token se configura en .env (PRECIO_MILLON_ENTRADA y PRECIO_MILLON_SALIDA).
Además de registrar cada corrida en logs/consumo.jsonl, este módulo calcula estadísticas
de costo por tarea (promedio, p50, p95, máximo) y proyecciones para pruebas de carga.
"""
import json
import math
import os
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

# Tarifa por millón de tokens configurable por entorno.
PRECIO_MILLON_ENTRADA = float(os.getenv("PRECIO_MILLON_ENTRADA", "0.60"))
PRECIO_MILLON_SALIDA = float(os.getenv("PRECIO_MILLON_SALIDA", "1.20"))


def calcular_costo_tokens(prompt_tokens: int, completion_tokens: int) -> dict:
    """Calcula el costo exacto desglosado en USD para entrada, salida y total."""
    costo_entrada = (max(0, prompt_tokens) / 1_000_000) * PRECIO_MILLON_ENTRADA
    costo_salida = (max(0, completion_tokens) / 1_000_000) * PRECIO_MILLON_SALIDA
    return {
        "entrada_usd": round(costo_entrada, 6),
        "salida_usd": round(costo_salida, 6),
        "total_usd": round(costo_entrada + costo_salida, 6),
    }


def percentil(valores: list[float], p: float) -> float:
    """Calcula el percentil p (0..100) sobre una lista numérica sin dependencias externas."""
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return round(float(ordenados[0]), 6)
    k = (len(ordenados) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(float(ordenados[int(k)]), 6)
    d0 = ordenados[f] * (c - k)
    d1 = ordenados[c] * (k - f)
    return round(float(d0 + d1), 6)


def registrar_uso(tarea_id, modelo, prompt_tokens, completion_tokens, latencia_segundos, traza=None):
    LOGS_DIR.mkdir(exist_ok=True)
    desglose = calcular_costo_tokens(prompt_tokens, completion_tokens)
    registro = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "tarea_id": tarea_id,
        "modelo": modelo,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latencia_segundos": round(latencia_segundos, 2),
        "costo_estimado_usd": desglose["total_usd"],
        "desglose_costo_usd": {
            "entrada_usd": desglose["entrada_usd"],
            "salida_usd": desglose["salida_usd"],
        },
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


def leer_registros_consumo(ruta_jsonl: Path | None = None) -> list[dict]:
    """Lee todos los registros válidos de consumo.jsonl."""
    ruta = Path(ruta_jsonl) if ruta_jsonl else (LOGS_DIR / "consumo.jsonl")
    if not ruta.exists():
        return []
    registros = []
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                registros.append(json.loads(linea))
    return registros


def calcular_resumen_costos(registros: list[dict] | None = None) -> dict:
    """Genera el reporte FinOps de Semana 3: promedio, p50, p95, máximo y desglose por flujo."""
    if registros is None:
        registros = leer_registros_consumo()
    if not registros:
        return {
            "total_tareas": 0,
            "costo_por_tarea_usd": {"promedio": 0.0, "p50": 0.0, "p95": 0.0, "maximo": 0.0, "total_acumulado": 0.0},
            "latencia_segundos": {"promedio": 0.0, "p50": 0.0, "p95": 0.0, "maximo": 0.0},
        }

    # Recalcular con la tarifa estándar para consistencia entre corridas históricas
    costos = []
    latencias = []
    prompts = []
    completions = []
    totales_tokens = []
    por_etapa = {
        "cotizacion_completa_3_tools": [],
        "consulta_inventario_2_tools": [],
        "busqueda_catalogo_1_tool": [],
    }

    for r in registros:
        pt = int(r.get("prompt_tokens", 0))
        ct = int(r.get("completion_tokens", 0))
        desglose = calcular_costo_tokens(pt, ct)
        c = desglose["total_usd"]
        costos.append(c)
        latencias.append(float(r.get("latencia_segundos", 0.0)))
        prompts.append(pt)
        completions.append(ct)
        totales_tokens.append(pt + ct)

        num_tools = len(r.get("herramientas") or [])
        if num_tools >= 3:
            por_etapa["cotizacion_completa_3_tools"].append(c)
        elif num_tools == 2:
            por_etapa["consulta_inventario_2_tools"].append(c)
        elif num_tools == 1:
            por_etapa["busqueda_catalogo_1_tool"].append(c)

    n = len(registros)
    costo_prom = sum(costos) / n
    costo_p95 = percentil(costos, 95)

    desglose_etapas = {}
    for etapa, vals in por_etapa.items():
        desglose_etapas[etapa] = {
            "ejecuciones": len(vals),
            "costo_promedio_usd": round(sum(vals) / len(vals), 6) if vals else 0.0,
            "costo_p50_usd": percentil(vals, 50) if vals else 0.0,
        }

    return {
        "total_tareas_analizadas": n,
        "modelo": registros[-1].get("modelo", "grok-4.7"),
        "tarifa_millon_tokens_usd": {
            "entrada": PRECIO_MILLON_ENTRADA,
            "salida": PRECIO_MILLON_SALIDA,
        },
        "tokens": {
            "promedio_entrada": round(sum(prompts) / n, 1),
            "promedio_salida": round(sum(completions) / n, 1),
            "promedio_total": round(sum(totales_tokens) / n, 1),
            "total_acumulado": sum(totales_tokens),
        },
        "costo_por_tarea_usd": {
            "promedio": round(costo_prom, 6),
            "p50": percentil(costos, 50),
            "p95": costo_p95,
            "minimo": round(min(costos), 6),
            "maximo": round(max(costos), 6),
            "total_acumulado": round(sum(costos), 6),
        },
        "latencia_segundos": {
            "promedio": round(sum(latencias) / n, 2),
            "p50": round(percentil(latencias, 50), 2),
            "p95": round(percentil(latencias, 95), 2),
            "maximo": round(max(latencias), 2),
        },
        "desglose_por_flujo": desglose_etapas,
        "proyeccion_1000_unidades": {
            "costo_esperado_promedio_usd": round(costo_prom * 1000, 2),
            "costo_escenario_p95_usd": round(costo_p95 * 1000, 2),
            "tokens_estimados_1000_unidades": int(round((sum(totales_tokens) / n) * 1000)),
        },
    }
