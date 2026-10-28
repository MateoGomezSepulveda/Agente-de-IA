"""Completa y consolida las 10 ejecuciones reales exigidas en la Semana 2."""
import asyncio
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.agent import ejecutar_agente

LOGS_PATH = RAIZ / "logs" / "consumo.jsonl"
RESULTADOS_PATH = RAIZ / "resultados" / "ejecuciones_s2.json"

# Casos reales para completar las ejecuciones faltantes
CASOS_PRUEBA = [
    ("data/fotos_prueba/test.jpg", None),
    ("data/fotos_prueba/test2.jpg", None),
    ("data/fotos_prueba/test3.jpg", None),
    ("data/fotos_prueba/test2.jpg", "data/fotos_prueba/test.jpg"),
]


def leer_ejecuciones_con_tools():
    if not LOGS_PATH.exists():
        return []
    ejecuciones = []
    with open(LOGS_PATH, "r", encoding="utf-8") as f:
        for linea in f:
            if not linea.strip():
                continue
            datos = json.loads(linea)
            if "herramientas" in datos and datos.get("herramientas"):
                ejecuciones.append(datos)
    return ejecuciones


async def main():
    ejecuciones = leer_ejecuciones_con_tools()
    print(f"Ejecuciones reales con tools actuales en logs: {len(ejecuciones)}/10")

    indice_caso = 0
    while len(ejecuciones) < 10:
        foto1, foto2 = CASOS_PRUEBA[indice_caso % len(CASOS_PRUEBA)]
        ruta1 = str(RAIZ / foto1)
        ruta2 = str(RAIZ / foto2) if foto2 else None

        print(f"\n-> Ejecutando corrida #{len(ejecuciones) + 1} con: {foto1}" + (f" + {foto2}" if foto2 else ""))
        resultado = await ejecutar_agente(ruta1, ruta2)
        print(f"   Estado obtenido: {resultado.get('estado')} | Tarea ID: {resultado.get('tarea_id')}")

        ejecuciones = leer_ejecuciones_con_tools()
        indice_caso += 1

    ultimas_10 = ejecuciones[-10:]
    RESULTADOS_PATH.parent.mkdir(exist_ok=True)

    resumen = {
        "total_ejecuciones_validadas": len(ultimas_10),
        "modelo": ultimas_10[-1].get("modelo", "grok-4.7"),
        "promedio_latencia_seg": round(sum(e["latencia_segundos"] for e in ultimas_10) / 10, 2),
        "promedio_tokens": round(sum(e["total_tokens"] for e in ultimas_10) / 10, 1),
        "costo_total_10_ejecuciones_usd": round(sum(e["costo_estimado_usd"] for e in ultimas_10), 6),
        "ejecuciones": ultimas_10,
    }

    with open(RESULTADOS_PATH, "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)

    print("\n====================================================")
    print("10 EJECUCIONES REALES COMPLETADAS Y EXPORTADAS")
    print(f"Reporte guardado en: {RESULTADOS_PATH}")
    print(f"Latencia promedio: {resumen['promedio_latencia_seg']} s")
    print(f"Tokens promedio: {resumen['promedio_tokens']}")
    print(f"Costo total (10 corridas): ${resumen['costo_total_10_ejecuciones_usd']} USD")
    print("====================================================")


if __name__ == "__main__":
    asyncio.run(main())
