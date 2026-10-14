import json

import pytest

from src.agent import ejecutar_agente, validar_respuesta
from src.llm_mock import ClienteMock


COTIZACION_VALIDA = {
    "estado": "cotizado",
    "pieza": {"id": "REP-001", "nombre": "Balatas Delanteras Cerámicas", "codigo_oem": "45022-TBA-A00", "confianza": 0.9},
    "vehiculos_compatibles": [
        {"marca": "Honda", "modelo": "Civic", "anio_desde": 2016, "anio_hasta": 2021},
        {"marca": "Honda", "modelo": "CR-V", "anio_desde": 2017, "anio_hasta": 2022},
    ],
    "cotizacion": {"precio_unitario": 850.5, "stock": 12, "ubicacion": "Pasillo 4, Estante B", "total": 850.5},
    "alternativas": [],
    "foto_adicional_solicitada": "",
    "motivo": "La foto coincide con balatas y hay stock.",
}


def _resultados_reales():
    return {
        "catalogo": {
            "REP-001": {
                "id_repuesto": "REP-001",
                "vehiculos_compatibles": COTIZACION_VALIDA["vehiculos_compatibles"],
            }
        },
        "inventario": {"REP-001": {"id_repuesto": "REP-001", "precio_unitario": 850.5, "stock": 12}},
        "cotizaciones": {"REP-001": {"id_repuesto": "REP-001", "precio_unitario": 850.5, "stock": 12, "total": 850.5}},
    }


def test_validacion_acepta_datos_que_salieron_de_las_tools():
    assert validar_respuesta(COTIZACION_VALIDA, 1, _resultados_reales())["estado"] == "cotizado"


def test_validacion_rechaza_precio_inventado():
    falsa = json.loads(json.dumps(COTIZACION_VALIDA))
    falsa["cotizacion"]["total"] = 1.0
    with pytest.raises(ValueError, match="alteró total"):
        validar_respuesta(falsa, 1, _resultados_reales())


def test_validacion_rechaza_compatibilidad_inventada():
    falsa = json.loads(json.dumps(COTIZACION_VALIDA))
    falsa["vehiculos_compatibles"] = [{"marca": "Ferrari", "modelo": "F40", "anio_desde": 1987, "anio_hasta": 1992}]
    with pytest.raises(ValueError, match="catálogo"):
        validar_respuesta(falsa, 1, _resultados_reales())


def test_validacion_rechaza_tercera_foto():
    datos = {"estado": "necesita_otra_foto", "pieza": {}, "vehiculos_compatibles": [], "cotizacion": None, "foto_adicional_solicitada": "el código", "motivo": "no se ve"}
    with pytest.raises(ValueError, match="máximo"):
        validar_respuesta(datos, 3, {"catalogo": {}, "inventario": {}, "cotizaciones": {}})


@pytest.mark.asyncio
async def test_bucle_completo_con_mock(tmp_path, monkeypatch):
    import src.db as db
    import src.tracking as tracking

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inventario.db")
    monkeypatch.setattr(tracking, "LOGS_DIR", tmp_path)
    import scripts.crear_bd as crear_bd

    monkeypatch.setattr(crear_bd, "DB_PATH", tmp_path / "inventario.db")
    crear_bd.inicializar_bd()

    guion = [
        ClienteMock.pedir_tool("buscar_en_catalogo", {"palabras_clave": ["balatas", "ceramica"]}),
        ClienteMock.pedir_tool("consultar_inventario", {"id_repuesto": "REP-001"}),
        ClienteMock.pedir_tool("generar_cotizacion", {"id_repuesto": "REP-001", "cantidad": 1}),
        ClienteMock.responder(COTIZACION_VALIDA),
    ]
    resultado = await ejecutar_agente("data/fotos_prueba/test.jpg", cliente=ClienteMock(guion))

    assert resultado["estado"] == "cotizado"
    assert resultado["cotizacion"]["total"] == 850.5
    assert resultado["vehiculos_compatibles"][0]["modelo"] == "Civic"
    assert len(resultado["tracking"]["herramientas"]) == 3
    assert (tmp_path / "consumo.jsonl").exists()


@pytest.mark.asyncio
async def test_respuesta_invalida_deriva_a_humano(tmp_path, monkeypatch):
    import src.tracking as tracking

    monkeypatch.setattr(tracking, "LOGS_DIR", tmp_path)
    cliente = ClienteMock([ClienteMock.responder("no es json")])
    resultado = await ejecutar_agente("data/fotos_prueba/test.jpg", cliente=cliente)
    assert resultado["estado"] == "derivar_a_humano"
    assert "validación" in resultado["motivo"]


@pytest.mark.asyncio
async def test_limite_de_iteraciones(tmp_path, monkeypatch):
    import src.tracking as tracking
    from src import config

    monkeypatch.setattr(tracking, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_ITERACIONES", 2)
    guion = [
        ClienteMock.pedir_tool("consultar_inventario", {"id_repuesto": "REP-999"}),
        ClienteMock.pedir_tool("consultar_inventario", {"id_repuesto": "REP-998"}),
        ClienteMock.responder(COTIZACION_VALIDA),
    ]
    resultado = await ejecutar_agente("data/fotos_prueba/test.jpg", cliente=ClienteMock(guion))
    assert resultado["estado"] == "derivar_a_humano"
    assert "máximo" in resultado["motivo"]
