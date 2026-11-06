import csv
import json
from pathlib import Path

import pytest

from src.carga import (
    BITACORA_CSV_PATH,
    RESUMEN_S4_PATH,
    ejecutar_corrida_carga,
)
from src.db import guardar_checkpoint_unidad, obtener_checkpoint_unidad


def test_checkpoint_idempotencia_sqlite(tmp_path, monkeypatch):
    import src.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_carga.db")
    registro = {
        "unidad_id": "UNI-0001",
        "tarea_id": "tarea_test01",
        "timestamp_inicio": "2026-11-05T20:00:00",
        "timestamp_fin": "2026-11-05T20:00:12",
        "entrada": "data/fotos_prueba/test2.jpg [original]",
        "categoria": "facil_con_stock",
        "herramientas_invocadas": "buscar_en_catalogo -> consultar_inventario -> generar_cotizacion",
        "estado_resultado": "cotizado",
        "id_repuesto": "REP-001",
        "nombre_repuesto": "Balatas Delanteras Cerámicas",
        "cotizacion_total_mxn": 850.5,
        "exito": True,
        "prompt_tokens": 12000,
        "completion_tokens": 300,
        "total_tokens": 12300,
        "latencia_segundos": 12.0,
        "costo_usd": 0.00756,
        "errores_detectados": "Ninguno",
        "recuperacion_agente": "Ejecución limpia en primer intento",
    }
    guardar_checkpoint_unidad(registro)
    recuperado = obtener_checkpoint_unidad("UNI-0001")
    assert recuperado is not None
    assert recuperado["unidad_id"] == "UNI-0001"
    assert recuperado["exito"] is True
    assert recuperado["costo_usd"] == 0.00756


@pytest.mark.asyncio
async def test_corrida_carga_exporta_bitacora_csv_y_json(tmp_path, monkeypatch):
    import src.db as db
    import scripts.crear_bd as crear_bd

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inventario.db")
    monkeypatch.setattr(crear_bd, "DB_PATH", tmp_path / "inventario.db")
    crear_bd.inicializar_bd()

    csv_out = tmp_path / "bitacora.csv"
    json_out = tmp_path / "bitacora.json"
    res_out = tmp_path / "resumen.json"

    resumen = await ejecutar_corrida_carga(
        total_unidades=20,
        horas_desatendido=12.0,
        concurrencia=4,
        modo="consolidado",
        usar_checkpoint=True,
        ruta_csv=csv_out,
        ruta_json=json_out,
        ruta_resumen=res_out,
    )
    assert resumen["metricas_principales_plataforma"]["total_unidades_procesadas"] == 20
    assert csv_out.exists()
    assert json_out.exists()
    assert res_out.exists()

    with open(csv_out, "r", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == 20
    assert "errores_detectados" in filas[0]
    assert "recuperacion_agente" in filas[0]


def test_bitacora_oficial_cumple_requisitos_s4():
    assert RESUMEN_S4_PATH.exists()
    assert BITACORA_CSV_PATH.exists()
    resumen = json.loads(RESUMEN_S4_PATH.read_text(encoding="utf-8"))
    m = resumen["metricas_principales_plataforma"]
    assert m["total_unidades_procesadas"] >= 1000
    assert m["horas_operacion_desatendida"] >= 12.0
    assert m["tasa_exito_pct"] >= 98.0
    assert m["costo_total_usd"] > 0
