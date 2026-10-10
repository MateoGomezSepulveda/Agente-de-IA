import sqlite3
import os
from pathlib import Path

def inicializar_bd():
    # Aseguramos que la carpeta data exista
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    db_path = data_dir / "inventario.db"
    
    # Conectamos a SQLite
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Crear tabla de inventario
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            id_repuesto TEXT PRIMARY KEY,
            precio_unitario REAL NOT NULL,
            stock INTEGER NOT NULL,
            ubicacion TEXT
        )
    ''')
    
    # Insertar datos de prueba
    repuestos = [
        ("REP-001", 850.50, 12, "Pasillo 4, Estante B"),
        ("REP-002", 220.00, 5, "Pasillo 1, Estante A")
    ]
    
    # Usamos REPLACE para que no duplique si corremos el script varias veces
    cursor.executemany('''
        INSERT OR REPLACE INTO inventario (id_repuesto, precio_unitario, stock, ubicacion)
        VALUES (?, ?, ?, ?)
    ''', repuestos)
    
    conn.commit()
    conn.close()
    
    print(f"Base de datos de inventario creada exitosamente en: {db_path}")

if __name__ == "__main__":
    inicializar_bd()