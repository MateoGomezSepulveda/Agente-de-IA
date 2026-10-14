"""Herramientas del agente.

El modelo solo pide que se ejecuten. Precios, stock, compatibilidades y
totales salen siempre de aquí, nunca de la memoria del modelo.
"""
import json
import unicodedata
from pathlib import Path

from src.db import guardar_cotizacion, obtener_inventario

CATALOGO_PATH = Path(__file__).resolve().parent.parent / "data" / "catalogo.json"
MAX_CANDIDATOS = 5


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def cargar_catalogo():
    with open(CATALOGO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def buscar_en_catalogo(palabras_clave):
    """Candidatos del catálogo ordenados por coincidencias, con sus vehículos.

    La compatibilidad se copia tal cual de la tabla del catálogo.
    """
    if isinstance(palabras_clave, str):
        palabras_clave = [palabras_clave]
    if not isinstance(palabras_clave, list) or not palabras_clave:
        return {"error": "palabras_clave debe ser una lista con al menos un término."}

    claves = []
    for palabra in palabras_clave:
        if not isinstance(palabra, str):
            continue
        limpia = _normalizar(palabra).strip()
        if len(limpia) >= 3:
            claves.append(limpia)
    if not claves:
        return {"error": "Ninguna palabra clave es usable (mínimo 3 caracteres)."}

    candidatos = []
    for item in cargar_catalogo():
        texto = _normalizar(
            " ".join(
                [
                    item.get("nombre", ""),
                    item.get("codigo_oem", ""),
                    " ".join(item.get("atributos_visuales", [])),
                ]
            )
        )
        coincidencias = sorted({clave for clave in claves if clave in texto})
        if coincidencias:
            candidatos.append(
                {
                    "id_repuesto": item["id_repuesto"],
                    "nombre": item["nombre"],
                    "codigo_oem": item.get("codigo_oem"),
                    "coincidencias": len(coincidencias),
                    "atributos_que_coinciden": coincidencias,
                    "vehiculos_compatibles": item.get("vehiculos_compatibles", []),
                }
            )

    candidatos.sort(key=lambda c: c["coincidencias"], reverse=True)
    return {
        "total": len(candidatos),
        "candidatos": candidatos[:MAX_CANDIDATOS],
        "aviso": "Vehículos tomados de la tabla de compatibilidad del catálogo.",
    }


def consultar_inventario(id_repuesto):
    """Stock, precio y ubicación desde SQLite. No inventa datos."""
    if not isinstance(id_repuesto, str) or not id_repuesto.strip():
        return {"error": "id_repuesto es obligatorio."}
    resultado = obtener_inventario(id_repuesto.strip())
    if resultado is None:
        return {"error": f"Repuesto {id_repuesto} no está en el inventario.", "en_inventario": False}
    return resultado


def generar_cotizacion(id_repuesto, cantidad=1, tarea_id=None):
    """Calcula el total en Python y lo guarda. El modelo no hace la cuenta."""
    if not isinstance(id_repuesto, str) or not id_repuesto.strip():
        return {"error": "id_repuesto es obligatorio."}
    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        return {"error": "cantidad debe ser un entero."}
    if cantidad < 1 or cantidad > 99:
        return {"error": "cantidad debe estar entre 1 y 99."}

    inventario = obtener_inventario(id_repuesto.strip())
    if not inventario or "error" in inventario:
        return {"error": f"No se puede cotizar {id_repuesto}: no está en el inventario."}
    if inventario["stock"] <= 0:
        return {
            "error": "Sin stock.",
            "id_repuesto": inventario["id_repuesto"],
            "stock": 0,
            "precio_unitario": inventario["precio_unitario"],
            "ubicacion": inventario["ubicacion"],
        }
    if cantidad > inventario["stock"]:
        return {
            "error": "La cantidad pedida supera el stock.",
            "stock": inventario["stock"],
            "precio_unitario": inventario["precio_unitario"],
        }

    precio = float(inventario["precio_unitario"])
    cotizacion = {
        "tarea_id": tarea_id,
        "id_repuesto": inventario["id_repuesto"],
        "cantidad": cantidad,
        "precio_unitario": precio,
        "stock": inventario["stock"],
        "ubicacion": inventario["ubicacion"],
        "total": round(precio * cantidad, 2),
    }
    cotizacion["cotizacion_id"] = guardar_cotizacion(cotizacion)
    return cotizacion


ESQUEMAS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_en_catalogo",
            "description": (
                "Busca repuestos por atributos visuales (tipo, material, forma, color, códigos). "
                "Devuelve candidatos y los vehículos compatibles de la tabla del catálogo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "palabras_clave": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Atributos vistos en la foto. Ejemplo: ['balatas', 'ceramica'].",
                    }
                },
                "required": ["palabras_clave"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_inventario",
            "description": "Consulta precio, stock y ubicación de un id_repuesto en el ERP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_repuesto": {
                        "type": "string",
                        "description": "ID oficial del catálogo, por ejemplo REP-001.",
                    }
                },
                "required": ["id_repuesto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generar_cotizacion",
            "description": (
                "Calcula y guarda la cotización de un repuesto que ya está en inventario. "
                "Úsala solo cuando la pieza identificada tenga confianza suficiente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id_repuesto": {"type": "string"},
                    "cantidad": {
                        "type": "integer",
                        "description": "Piezas a cotizar. Por defecto 1.",
                    },
                },
                "required": ["id_repuesto"],
            },
        },
    },
]

FUNCIONES = {
    "buscar_en_catalogo": buscar_en_catalogo,
    "consultar_inventario": consultar_inventario,
    "generar_cotizacion": generar_cotizacion,
}
