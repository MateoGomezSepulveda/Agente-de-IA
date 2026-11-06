"""Día 21 (Semana 3): Consolida los reportes oficiales de Evaluación y Costos por Tarea en resultados/."""
import asyncio
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.generar_carga import generar_unidades_carga
from src.evaluacion import (
    RESULTADOS_EVAL_PATH,
    ejecutar_evaluacion_sistematica,
    generar_dataset_evaluacion,
)
from src.tracking import calcular_resumen_costos

RESULTADOS_COSTOS_PATH = RAIZ / "resultados" / "costos_s3.json"


async def main():
    print("1. Generando dataset etiquetado y ejecutando evaluación sistemática de Semana 3 (100 casos)...")
    generar_dataset_evaluacion()
    reporte_eval = await ejecutar_evaluacion_sistematica()

    print("2. Calculando reporte FinOps de costos por tarea (promedio, p50, p95, máximo)...")
    resumen_costos = calcular_resumen_costos()
    RESULTADOS_COSTOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTADOS_COSTOS_PATH.write_text(
        json.dumps(resumen_costos, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("3. Generando manifiesto de 1,000 unidades para ensayo y Semana 4...")
    manifiesto_carga = generar_unidades_carga(total_unidades=1000)

    metricas = reporte_eval["metricas_calidad_s3"]
    costos = resumen_costos["costo_por_tarea_usd"]

    print("\n========================================================")
    print("REPORTES SEMANA 3 GENERADOS EXITOSAMENTE")
    print(f"- Evaluación guardada en : {RESULTADOS_EVAL_PATH}")
    print(f"- Costos guardados en    : {RESULTADOS_COSTOS_PATH}")
    print(f"- Precisión Top-1        : {metricas['precision_pieza_top_1_pct']}% (Meta >= 80%)")
    print(f"- Precisión Top-3        : {metricas['precision_pieza_top_3_pct']}% (Meta >= 92%)")
    print(f"- Exactitud de Estado    : {metricas['exactitud_estado_esperado_pct']}% (Meta >= 90%)")
    print(f"- Alucinaciones          : {metricas['alucinaciones_detectadas']} (Meta = 0)")
    print(f"- Costo Promedio / Tarea : ${costos['promedio']} USD (p50=${costos['p50']} | p95=${costos['p95']})")
    print(f"- Unidades Carga Listas  : {manifiesto_carga['total_unidades']}")
    print("========================================================")


if __name__ == "__main__":
    asyncio.run(main())
