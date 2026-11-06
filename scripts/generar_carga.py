"""Día 20 (Semana 3): Genera el set de 1,000 unidades de trabajo en data/carga/unidades_1000.json.

Parte de los 100 casos base de evaluación (data/eval/dataset_eval.json) y genera 10 lotes
con variaciones controladas documentadas (original, rotación, brillo, contraste, recorte, etc.),
declarando explícitamente qué unidades son casos base y cuáles son variaciones de estrés.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.evaluacion import EVAL_PATH, generar_dataset_evaluacion

CARGA_DIR = RAIZ / "data" / "carga"
UNIDADES_PATH = CARGA_DIR / "unidades_1000.json"

VARIACIONES = [
    "original_sin_alteracion",
    "rotacion_leve_5_grados",
    "ajuste_brillo_mas_10_pct",
    "ajuste_brillo_menos_10_pct",
    "recorte_central_90_pct",
    "contraste_alto_taller",
    "iluminacion_calida_almacen",
    "iluminacion_fria_mostrador",
    "compresion_optimizada_movil",
    "angulo_secundario_mostrador",
]


def generar_unidades_carga(total_unidades: int = 1000, ruta_salida: Path | None = None) -> dict:
    if not EVAL_PATH.exists():
        casos_base = generar_dataset_evaluacion(EVAL_PATH)
    else:
        casos_base = json.loads(EVAL_PATH.read_text(encoding="utf-8"))

    ruta = Path(ruta_salida) if ruta_salida else UNIDADES_PATH
    ruta.parent.mkdir(parents=True, exist_ok=True)

    unidades = []
    for i in range(total_unidades):
        caso = casos_base[i % len(casos_base)]
        lote_idx = i // len(casos_base)
        variacion = VARIACIONES[lote_idx % len(VARIACIONES)]
        unidades.append(
            {
                "unidad_id": f"UNI-{i + 1:04d}",
                "orden": i + 1,
                "caso_base_id": caso["caso_id"],
                "categoria": caso["categoria"],
                "imagen": caso["imagen"],
                "segunda_imagen": caso.get("segunda_imagen"),
                "variacion_visual": variacion,
                "es_repeticion_variada": lote_idx > 0,
                "atributos_observados": caso["atributos_observados"],
                "esperado": caso["esperado"],
            }
        )

    manifiesto = {
        "total_unidades": len(unidades),
        "casos_base_unicos": len(casos_base),
        "factor_expansion_variaciones": len(VARIACIONES),
        "declaracion_transparencia": (
            "Las 1,000 unidades se componen de 100 casos etiquetados base que cubren las 40 refacciones "
            "del catálogo y casos de borde (sin stock, fuera de ERP, ambiguos de 2da foto y fuera de catálogo), "
            "multiplicados por 10 perfiles de variación de captura en mostrador/taller."
        ),
        "unidades": unidades,
    }
    ruta.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifiesto


if __name__ == "__main__":
    manifiesto = generar_unidades_carga()
    print(f"Set de carga generado en {UNIDADES_PATH}: {manifiesto['total_unidades']} unidades listas.")
