import json

from src.tools import buscar_en_catalogo, consultar_inventario, generar_cotizacion


def test_catalogo_tiene_el_minimo_de_la_semana():
    from src.tools import cargar_catalogo

    catalogo = cargar_catalogo()
    assert len(catalogo) >= 30
    assert all(item["vehiculos_compatibles"] for item in catalogo)


def test_busqueda_devuelve_compatibilidad_del_catalogo():
    resultado = buscar_en_catalogo(["balatas", "ceramica"])
    assert resultado["total"] >= 1
    primero = resultado["candidatos"][0]
    assert primero["id_repuesto"] == "REP-001"
    assert primero["vehiculos_compatibles"][0]["marca"] == "Honda"


def test_busqueda_ignora_acentos_y_mayusculas():
    resultado = buscar_en_catalogo(["Cerámica"])
    assert any(c["id_repuesto"] == "REP-001" for c in resultado["candidatos"])


def test_busqueda_sin_coincidencias():
    resultado = buscar_en_catalogo(["turbocompresor"])
    assert resultado["total"] == 0
    assert resultado["candidatos"] == []


def test_busqueda_rechaza_entrada_inutil():
    assert "error" in buscar_en_catalogo([])
    assert "error" in buscar_en_catalogo(["a", "de"])
    assert "error" in buscar_en_catalogo(None)


def test_inventario_existente_sale_de_sqlite():
    resultado = consultar_inventario("REP-001")
    assert resultado["precio_unitario"] == 850.5
    assert resultado["stock"] == 12
    assert resultado["ubicacion"]


def test_inventario_inexistente_no_inventa_precio():
    resultado = consultar_inventario("REP-999")
    assert "error" in resultado
    assert "precio_unitario" not in resultado


def test_cotizacion_la_calcula_el_codigo(tmp_path, monkeypatch):
    import src.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inventario.db")
    import scripts.crear_bd as crear_bd

    monkeypatch.setattr(crear_bd, "DB_PATH", tmp_path / "inventario.db")
    crear_bd.inicializar_bd()

    cotizacion = generar_cotizacion("REP-002", cantidad=3, tarea_id="test")
    assert cotizacion["precio_unitario"] == 220.0
    assert cotizacion["total"] == 660.0
    assert cotizacion["cotizacion_id"] == 1


def test_cotizacion_sin_stock_no_calcula_total(tmp_path, monkeypatch):
    import src.db as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "inventario.db")
    import scripts.crear_bd as crear_bd

    monkeypatch.setattr(crear_bd, "DB_PATH", tmp_path / "inventario.db")
    crear_bd.inicializar_bd()

    resultado = generar_cotizacion("REP-037")
    assert resultado["error"] == "Sin stock."
    assert "total" not in resultado


def test_cotizacion_rechaza_cantidad_invalida():
    assert "error" in generar_cotizacion("REP-001", cantidad=0)
    assert "error" in generar_cotizacion("REP-001", cantidad="muchas")
    assert "error" in generar_cotizacion("REP-040")
