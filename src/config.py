"""Configuración central del agente: rutas, límites y cliente de Platica."""
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# --- Rutas del proyecto ---
RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
LOGS_DIR = RAIZ / "logs"
RESULTADOS_DIR = RAIZ / "resultados"

# --- Modelo y límites de seguridad (control de costos) ---
MODEL = os.getenv("PLATICA_MODEL", "grok-4.7")
MAX_ITERACIONES = int(os.getenv("MAX_ITERACIONES", "6"))  # tope de vueltas del bucle de tools
MAX_FOTOS_EXTRA = 1  # el reto permite como máximo una segunda foto


def crear_cliente() -> AsyncOpenAI:
    """Crea el cliente apuntando al endpoint de Platica.

    Las credenciales se leen aquí (y no al importar el módulo) para que
    las pruebas con el LLM simulado no necesiten una clave real.
    """
    base_url = os.getenv("PLATICA_BASE_URL")
    api_key = os.getenv("PLATICA_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError(
            "Faltan PLATICA_BASE_URL o PLATICA_API_KEY en el archivo .env"
        )
    return AsyncOpenAI(base_url=base_url, api_key=api_key)