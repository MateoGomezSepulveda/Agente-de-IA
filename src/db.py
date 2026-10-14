"""Acceso de solo lectura al ERP simulado (SQLite)."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "inventario.db"


def obtener_inventario(id_repuesto: str):
    """Precio, stock y ubicación de un repuesto. None si no está en el ERP."""
    if not isinstance(id_repuesto, str) or not id_repuesto.strip():
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id_repuesto, precio_unitario, stock, ubicacion FROM inventario WHERE id_repuesto = ?",
            (id_repuesto.strip(),),
        )
        fila = cursor.fetchone()
        conn.close()
        return dict(fila) if fila else None
    except sqlite3.Error as e:
        return {"error": f"No se pudo leer el inventario: {e}"}


def guardar_cotizacion(cotizacion: dict) -> int:
    """Persiste una cotización ya calculada por el código. Devuelve su id."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarea_id TEXT,
            id_repuesto TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            total REAL NOT NULL,
            stock INTEGER NOT NULL,
            creada_en TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO cotizaciones
            (tarea_id, id_repuesto, cantidad, precio_unitario, total, stock)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            cotizacion.get("tarea_id"),
            cotizacion["id_repuesto"],
            cotizacion["cantidad"],
            cotizacion["precio_unitario"],
            cotizacion["total"],
            cotizacion["stock"],
        ),
    )
    cotizacion_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return cotizacion_id
