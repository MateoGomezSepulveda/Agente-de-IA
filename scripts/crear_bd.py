"""Genera data/inventario.db a partir de data/catalogo.json.

La compatibilidad vive en el catálogo (fuente de verdad). Esta base solo
simula el ERP: precio, stock y ubicación. Algunos IDs se dejan sin stock
o fuera de inventario a propósito, para los casos de borde de la Semana 1.
"""
import json
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CATALOGO = RAIZ / "data" / "catalogo.json"
DB_PATH = RAIZ / "data" / "inventario.db"

# Precios y stock fijos (no los inventa el modelo). None = no está en el ERP.
INVENTARIO = {
    "REP-001": (850.50, 12, "Pasillo 4, Estante B"),
    "REP-002": (220.00, 5, "Pasillo 1, Estante A"),
    "REP-003": (340.00, 8, "Pasillo 1, Estante C"),
    "REP-004": (185.00, 40, "Pasillo 2, Estante A"),
    "REP-005": (1450.00, 3, "Pasillo 6, Estante D"),
    "REP-006": (980.00, 6, "Pasillo 4, Estante A"),
    "REP-007": (760.00, 4, "Pasillo 3, Estante B"),
    "REP-008": (540.00, 7, "Pasillo 3, Estante C"),
    "REP-009": (3200.00, 2, "Pasillo 7, Estante A"),
    "REP-010": (2100.00, 2, "Pasillo 7, Estante B"),
    "REP-011": (2750.00, 1, "Pasillo 5, Estante A"),
    "REP-012": (310.00, 15, "Pasillo 2, Estante D"),
    "REP-013": (1680.00, 3, "Pasillo 3, Estante A"),
    "REP-014": (890.00, 10, "Pasillo 2, Estante B"),
    "REP-015": (1250.00, 6, "Pasillo 2, Estante C"),
    "REP-016": (740.00, 9, "Pasillo 2, Estante A"),
    "REP-017": (4300.00, 1, "Pasillo 8, Estante A"),
    "REP-018": (2100.00, 2, "Pasillo 8, Estante B"),
    "REP-019": (980.00, 4, "Pasillo 8, Estante C"),
    "REP-020": (3500.00, 2, "Pasillo 9, Estante A"),
    "REP-021": (1120.00, 5, "Pasillo 6, Estante A"),
    "REP-022": (280.00, 18, "Pasillo 6, Estante B"),
    "REP-023": (4600.00, 1, "Pasillo 6, Estante C"),
    "REP-024": (2400.00, 2, "Pasillo 6, Estante D"),
    "REP-025": (690.00, 8, "Pasillo 4, Estante C"),
    "REP-026": (1850.00, 3, "Pasillo 5, Estante B"),
    "REP-027": (2200.00, 2, "Pasillo 5, Estante C"),
    "REP-028": (870.00, 4, "Pasillo 5, Estante D"),
    "REP-029": (760.00, 5, "Pasillo 4, Estante D"),
    "REP-030": (5400.00, 1, "Pasillo 9, Estante B"),
    "REP-031": (1600.00, 3, "Pasillo 9, Estante C"),
    "REP-032": (420.00, 6, "Pasillo 3, Estante D"),
    "REP-033": (1900.00, 2, "Pasillo 8, Estante D"),
    "REP-034": (3800.00, 1, "Pasillo 7, Estante C"),
    "REP-035": (950.00, 4, "Pasillo 8, Estante E"),
    "REP-036": (640.00, 7, "Pasillo 2, Estante E"),
    "REP-037": (1100.00, 0, "Pasillo 2, Estante F"),  # sin stock
    "REP-038": (2300.00, 0, "Pasillo 3, Estante E"),  # sin stock
    # REP-039 y REP-040 existen en el catálogo pero no en el ERP.
}


def inicializar_bd():
    DB_PATH.parent.mkdir(exist_ok=True)
    catalogo = json.loads(CATALOGO.read_text(encoding="utf-8"))
    ids_catalogo = {item["id_repuesto"] for item in catalogo}
    desconocidos = set(INVENTARIO) - ids_catalogo
    if desconocidos:
        raise SystemExit(f"IDs de inventario que no están en el catálogo: {desconocidos}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventario (
            id_repuesto TEXT PRIMARY KEY,
            precio_unitario REAL NOT NULL,
            stock INTEGER NOT NULL,
            ubicacion TEXT
        )
        """
    )
    cursor.execute("DELETE FROM inventario")
    cursor.executemany(
        """
        INSERT INTO inventario (id_repuesto, precio_unitario, stock, ubicacion)
        VALUES (?, ?, ?, ?)
        """,
        [(id_, precio, stock, ubicacion) for id_, (precio, stock, ubicacion) in INVENTARIO.items()],
    )
    conn.commit()
    conn.close()
    print(f"Inventario creado en {DB_PATH} ({len(INVENTARIO)} piezas).")


if __name__ == "__main__":
    inicializar_bd()
