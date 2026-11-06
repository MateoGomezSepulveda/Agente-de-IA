import json

import pytest

from scripts.generar_carga import generar_unidades_carga
from src.evaluacion import (
    ejecutar_evaluacion_sistematica,
    generar_dataset_evaluacion,
    validar_integridad_datos,
)
from src.tracking import calcular_costo_tokens, calcular_resumen_costos, percentil


def test_integridad_catalogo_e_inventario():
    reporte = validar_integridad_datos()
    assert reporte["integro"] is True
    assert reporte["total_catalogo"] == 40
    assert reporte["total_en_erp"] == 38
    assert reporte["repuestos_con_stock"] == 36
    assert "REP-037" in reporte["repuestos_sin_stock_controlado"]
    assert "REP-039" in reporte["repuestos_fuera_erp_controlado"]


def test_calculo_percentiles_y_finops():
    valores = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentil(valores, 50) == 30.0
    assert percentil(valores, 95) == 48.0

    desglose = calcular_costo_tokens(1_000_000, 500_000)
    assert desglose["entrada_usd"] == 0.60
    assert desglose["salida_usd"] == 0.60
    assert desglose["total_usd"] == 1.20

    resumen = calcular_resumen_costos(
        [
            {"prompt_tokens": 5000, "completion_tokens": 250, "latencia_segundos": 10.0, "herramientas": [{}]},
            {"prompt_tokens": 10000, "completion_tokens": 300, "latencia_segundos": 14.0, "herramientas": [{}, {}, {}]},
        ]
    )
    assert resumen["total_tareas_analizadas"] == 2
    assert resumen["costo_por_tarea_usd"]["p50"] > 0
    assert resumen["proyeccion_1000_unidades"]["tokens_estimados_1000_unidades"] == 7775000


@pytest.mark.asyncio
async def test_evaluacion_sistematica_cumple_metas_s3(tmp_path):
    ruta_ds = tmp_path / "dataset_eval.json"
    ruta_out = tmp_path / "evaluacion_s3.json"
    casos = generar_dataset_evaluacion(ruta_ds)
    assert len(casos) == 100

    reporte = await ejecutar_evaluacion_sistematica(ruta_ds, ruta_out)
    metricas = reporte["metricas_calidad_s3"]
    assert metricas["cumple_top_1"] is True
    assert metricas["cumple_top_3"] is True
    assert metricas["cumple_estado"] is True
    assert metricas["alucinaciones_detectadas"] == 0
    assert ruta_out.exists()


def test_generacion_1000_unidades_carga(tmp_path):
    ruta_carga = tmp_path / "unidades_1000.json"
    manifiesto = generar_unidades_carga(total_unidades=1000, ruta_salida=ruta_carga)
    assert manifiesto["total_unidades"] == 1000
    assert manifiesto["unidades"][0]["unidad_id"] == "UNI-0001"
    assert manifiesto["unidades"][0]["es_repeticion_variada"] is False
    assert manifiesto["unidades"][-1]["unidad_id"] == "UNI-1000"
    assert manifiesto["unidades"][-1]["es_repeticion_variada"] is True


def test_mejora_s3_busqueda_frases_compuestas_y_optimizacion_vision():
    from src.tools import buscar_en_catalogo
    from src.vision import procesar_imagen_base64

    res = buscar_en_catalogo(["balatas", "pastillas de freno"])
    assert res["candidatos"][0]["id_repuesto"] == "REP-001"
    assert res["candidatos"][0]["coincidencias"] == 2

    b64 = procesar_imagen_base64("data/fotos_prueba/test2.jpg", optimizar=True)
    assert b64.startswith("/9j/")
