import json
from pathlib import Path
from src.db import obtener_inventario

CATALOGO_PATH = Path(__file__).resolve().parent.parent / "data" / "catalogo.json"

def cargar_catalogo():
    with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def buscar_en_catalogo(palabras_clave):
    """
    Busca repuestos en el catálogo basándose en palabras clave.
    Retorna la información del repuesto y sus vehículos compatibles.
    """
    catalogo = cargar_catalogo()
    resultados = []
    
    # Convertimos a minúsculas para buscar sin importar mayúsculas
    claves = [p.lower() for p in palabras_clave]
    
    for item in catalogo:
        texto_item = f"{item['nombre']} {' '.join(item['atributos_visuales'])}".lower()
        
        # Si alguna palabra clave coincide, agregamos el repuesto a resultados
        if any(clave in texto_item for clave in claves):
            resultados.append(item)
            
    return resultados

def consultar_inventario(id_repuesto):
    """
    Consulta la BD de inventario (precio y stock) para un ID específico.
    """
    resultado = obtener_inventario(id_repuesto)
    if resultado:
        return resultado
    return {"error": f"Repuesto {id_repuesto} no encontrado en el inventario."}

# --- PRUEBA LOCAL ---
if __name__ == "__main__":
    print("🔍 Prueba de Catálogo (buscando 'balatas'):")
    print(buscar_en_catalogo(["balatas", "frenos"]))
    
    print("\n📦 Prueba de Inventario (buscando REP-001):")
    print(consultar_inventario("REP-001"))