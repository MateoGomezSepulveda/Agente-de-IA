import sqlite3
from pathlib import Path

# Ruta absoluta a la base de datos
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "inventario.db"

def obtener_inventario(id_repuesto: str):
    """Busca un repuesto en el inventario de SQLite por su ID."""
    try:
        conn = sqlite3.connect(DB_PATH)
        # Esto permite acceder a las columnas por su nombre como si fuera un diccionario
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        
        # Consultamos el precio, stock y ubicación
        cursor.execute(
            "SELECT id_repuesto, precio_unitario, stock, ubicacion FROM inventario WHERE id_repuesto = ?", 
            (id_repuesto,)
        )
        fila = cursor.fetchone()
        conn.close()
        
        if fila:
            return dict(fila)
        return None
    except Exception as e:
        print(f"Error accediendo a la BD: {e}")
        return None