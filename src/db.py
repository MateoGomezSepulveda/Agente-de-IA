"""Acceso al ERP de inventario OEM automotriz y persistencia de checkpoints de carga en SQLite."""
import json
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


def inicializar_tabla_carga() -> None:
    """Crea la tabla de checkpoints para la Semana 4 (idempotencia y reanudación)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints_carga (
            unidad_id TEXT PRIMARY KEY,
            tarea_id TEXT NOT NULL,
            timestamp_inicio TEXT NOT NULL,
            timestamp_fin TEXT NOT NULL,
            entrada TEXT NOT NULL,
            categoria TEXT,
            herramientas_invocadas TEXT,
            estado_resultado TEXT NOT NULL,
            id_repuesto TEXT,
            nombre_repuesto TEXT,
            cotizacion_total_mxn REAL DEFAULT 0.0,
            exito INTEGER NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            latencia_segundos REAL DEFAULT 0.0,
            costo_usd REAL DEFAULT 0.0,
            errores_detectados TEXT,
            recuperacion_agente TEXT,
            payload_json TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def obtener_checkpoint_unidad(unidad_id: str) -> dict | None:
    """Devuelve el checkpoint de una unidad si ya fue procesada con éxito (idempotencia)."""
    inicializar_tabla_carga()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM checkpoints_carga WHERE unidad_id = ? AND exito = 1",
        (unidad_id,),
    )
    fila = cursor.fetchone()
    conn.close()
    if not fila:
        return None
    datos = dict(fila)
    datos["exito"] = bool(datos["exito"])
    return datos


def guardar_checkpoint_unidad(registro: dict) -> None:
    """Guarda o actualiza el resultado de una unidad en SQLite para reanudación ante caídas."""
    inicializar_tabla_carga()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO checkpoints_carga (
            unidad_id, tarea_id, timestamp_inicio, timestamp_fin, entrada,
            categoria, herramientas_invocadas, estado_resultado, id_repuesto,
            nombre_repuesto, cotizacion_total_mxn, exito, prompt_tokens,
            completion_tokens, total_tokens, latencia_segundos, costo_usd,
            errores_detectados, recuperacion_agente, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            registro["unidad_id"],
            registro["tarea_id"],
            registro["timestamp_inicio"],
            registro["timestamp_fin"],
            registro["entrada"],
            registro.get("categoria", ""),
            registro.get("herramientas_invocadas", ""),
            registro["estado_resultado"],
            registro.get("id_repuesto", ""),
            registro.get("nombre_repuesto", ""),
            float(registro.get("cotizacion_total_mxn", 0.0)),
            1 if registro.get("exito", True) else 0,
            int(registro.get("prompt_tokens", 0)),
            int(registro.get("completion_tokens", 0)),
            int(registro.get("total_tokens", 0)),
            float(registro.get("latencia_segundos", 0.0)),
            float(registro.get("costo_usd", 0.0)),
            registro.get("errores_detectados", "Ninguno"),
            registro.get("recuperacion_agente", "Ejecución limpia en primer intento"),
            json.dumps(registro, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def listar_checkpoints_carga() -> list[dict]:
    """Devuelve todas las unidades registradas en orden de unidad_id."""
    inicializar_tabla_carga()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM checkpoints_carga ORDER BY unidad_id ASC")
    filas = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for f in filas:
        f["exito"] = bool(f["exito"])
    return filas


def guardar_lote_checkpoints(registros: list[dict]) -> None:
    """Persiste un lote de unidades en una sola transacción atómica de SQLite."""
    if not registros:
        return
    inicializar_tabla_carga()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT OR REPLACE INTO checkpoints_carga (
            unidad_id, tarea_id, timestamp_inicio, timestamp_fin, entrada,
            categoria, herramientas_invocadas, estado_resultado, id_repuesto,
            nombre_repuesto, cotizacion_total_mxn, exito, prompt_tokens,
            completion_tokens, total_tokens, latencia_segundos, costo_usd,
            errores_detectados, recuperacion_agente, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["unidad_id"],
                r["tarea_id"],
                r["timestamp_inicio"],
                r["timestamp_fin"],
                r["entrada"],
                r.get("categoria", ""),
                r.get("herramientas_invocadas", ""),
                r["estado_resultado"],
                r.get("id_repuesto", ""),
                r.get("nombre_repuesto", ""),
                float(r.get("cotizacion_total_mxn", 0.0)),
                1 if r.get("exito", True) else 0,
                int(r.get("prompt_tokens", 0)),
                int(r.get("completion_tokens", 0)),
                int(r.get("total_tokens", 0)),
                float(r.get("latencia_segundos", 0.0)),
                float(r.get("costo_usd", 0.0)),
                r.get("errores_detectados", "Ninguno"),
                r.get("recuperacion_agente", "Ejecución limpia en primer intento"),
                json.dumps(r, ensure_ascii=False),
            )
            for r in registros
        ],
    )
    conn.commit()
    conn.close()
