"""Servidor API Asíncrono (Starlette + Uvicorn) para Platica AI Studio (v2.0).

Conecta el Frontend web con:
1. Agente Autónomo de Ingeniería de Software estilo Gemini / chat.py con Streaming SSE,
   heartbeats anti-timeout, progreso en vivo de generación de código y 6 herramientas reales:
   - listar_directorio: explorar carpetas y archivos del workspace
   - leer_archivo: leer código completo o por rango exacto de líneas (hasta 48k chars sin truncar)
   - escribir_archivo: crear archivos nuevos o sobrescribirlos
   - editar_archivo: modificar fragmentos exactos de código sin reescribir todo el archivo
   - buscar_en_codigo: buscar funciones, clases o texto en el repositorio
   - ejecutar_comando: ejecutar comandos reales en PowerShell (pytest, npm run build, git, etc.)
2. Agente autónomo multimodal de refacciones (ejecutar_agente + 3 tools reales).
3. Telemetría FinOps, catálogo OEM e inventario SQLite en tiempo real.
"""
import asyncio
import json
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

import httpx
import openai
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

import src.db as db_mod
from src import config
from src.agent import ejecutar_agente
from src.tools import cargar_catalogo
from src.tracking import calcular_costo_tokens

FOTOS_PRUEBA_DIR = config.DATA_DIR / "fotos_prueba"
FOTOS_SUBIDAS_DIR = config.DATA_DIR / "fotos_subidas"
UI_DB_PATH = config.LOGS_DIR / "inventario_ui.db"
MAX_ITERACIONES_CHAT = 20


MAX_TOKENS_SALIDA_CHAT = 16384
MAX_BYTES_FOTO_SUBIDA = 5 * 1024 * 1024  # mismo límite que src/vision.py


def _detectar_extension_imagen(contenido: bytes) -> str | None:
    """Devuelve la extensión real según firma binaria (magic bytes) o None si no es imagen válida."""
    if contenido.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return ".webp"
    return None


def _guardar_foto_subida(contenido: bytes, etiqueta: str) -> Path:
    """Valida y persiste la foto del escáner en data/fotos_subidas/ con nombre único.

    Nombre: AAAAMMDD_HHMMSS_<uuid8>_<etiqueta>.<ext> (la extensión sale de la firma binaria real).
    Lanza ValueError si el archivo está vacío, pesa más de 5 MB o no es JPEG/PNG/WEBP.
    """
    if not contenido:
        raise ValueError("La fotografía está vacía.")
    if len(contenido) > MAX_BYTES_FOTO_SUBIDA:
        raise ValueError("La fotografía supera el límite de 5 MB.")
    extension = _detectar_extension_imagen(contenido)
    if extension is None:
        raise ValueError("El archivo no es una imagen JPEG, PNG o WEBP válida.")
    FOTOS_SUBIDAS_DIR.mkdir(parents=True, exist_ok=True)
    sello = time.strftime("%Y%m%d_%H%M%S")
    destino = FOTOS_SUBIDAS_DIR / f"{sello}_{uuid.uuid4().hex[:8]}_{etiqueta}{extension}"
    destino.write_bytes(contenido)
    return destino


def _registrar_vinculo_fotos(tarea_id: str | None, rutas: list[str]) -> None:
    """Deja en logs/fotos_subidas.jsonl qué fotos pertenecen a cada tarea_id (trazabilidad)."""
    if not rutas:
        return
    config.LOGS_DIR.mkdir(exist_ok=True)
    registro = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tarea_id": tarea_id,
        "fotos": rutas,
    }
    with open(config.LOGS_DIR / "fotos_subidas.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")

DIRS_IGNORADOS_BUSQUEDA = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    ".venv",
    "venv",
}

# --- 1. ESQUEMAS DE HERRAMIENTAS DEL CHAT AGÉNTICO ---
# Nota de arquitectura sobre https://api.reto.pltk.mx/v1:
# El proxy Cloudflare de Platica almacena en búfer los `tool_calls` JSON grandes (>6 KB) y corta a ~100s.
# Por ello, SOLO las herramientas ligeras (<200 chars de argumentos) van en `tools` JSON, mientras que
# `escribir_archivo` y `editar_archivo` fluyen por streaming XML directo en `delta.content` sin búfer.
TOOLS_CHAT_AGENTE = [
    {
        "type": "function",
        "function": {
            "name": "listar_directorio",
            "description": "Lista los archivos y subcarpetas dentro de una ruta del proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta relativa o absoluta a explorar. Por defecto '.' (raíz del proyecto).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leer_archivo",
            "description": "Lee el contenido de un archivo de código o texto por rango de líneas (recomendado indicar linea_inicio y linea_fin).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta relativa o absoluta del archivo a inspeccionar.",
                    },
                    "linea_inicio": {
                        "type": "integer",
                        "description": "Línea inicial opcional (empezando en 1).",
                    },
                    "linea_fin": {
                        "type": "integer",
                        "description": "Línea final opcional (inclusiva).",
                    },
                },
                "required": ["ruta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_codigo",
            "description": "Busca texto literal o expresión regular (ej. 'endpoint_diagnosticar|endpoint_metricas') en el proyecto y devuelve archivo y línea exacta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patron": {
                        "type": "string",
                        "description": "Texto o expresión regular a buscar (insensible a mayúsculas).",
                    },
                    "ruta": {
                        "type": "string",
                        "description": "Archivo o carpeta opcional donde limitar la búsqueda. Por defecto '.'.",
                    },
                },
                "required": ["patron"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ejecutar_comando",
            "description": "Ejecuta un comando corto en PowerShell (ej. 'cd Frontend; npm run build', 'python -m pytest -q'). PROHIBIDO usarlo para crear o editar código de archivos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "comando": {
                        "type": "string",
                        "description": "Comando corto de terminal a ejecutar (máx. 400 caracteres).",
                    }
                },
                "required": ["comando"],
            },
        },
    },
]

SYSTEM_CHAT_AGENTE = (
    "Eres Platica Agent (impulsado por grok-4.7), un Agente Autónomo de Ingeniería de Software "
    "ejecutándose en el workspace local del usuario en Windows.\n"
    "Cuentas con 6 capacidades reales conectadas a disco y terminal:\n"
    "1. `listar_directorio` (tool JSON): explora carpetas y archivos.\n"
    "2. `buscar_en_codigo` (tool JSON): acepta texto o regex con `|` para hallar líneas exactas al instante.\n"
    "3. `leer_archivo` (tool JSON): lee rangos puntuales (`linea_inicio` y `linea_fin`). Evita leer archivos enormes enteros; usa primero `buscar_en_codigo`.\n"
    "4. `ejecutar_comando` (tool JSON): SOLO para comandos cortos de terminal (`cd Frontend; npm run build`, `python -m pytest -q`, `git status`). NUNCA escribas archivos con PowerShell.\n"
    "5. `<escribir_archivo>` (acción XML en streaming directo): ÚNICA forma de crear archivos nuevos o reescribir un archivo completo.\n"
    "6. `<editar_archivo>` (acción XML en streaming directo): ÚNICA forma de reemplazar un bloque exacto en un archivo existente.\n\n"
    "FORMATO EXACTO PARA CREAR O REESCRIBIR UN ARCHIVO COMPLETO:\n"
    "<escribir_archivo ruta=\"ruta/relativa/archivo.tsx\">\n"
    "...código completo aquí (sin triples backticks)...\n"
    "</escribir_archivo>\n\n"
    "FORMATO EXACTO PARA EDITAR UN BLOQUE CORTO DE UN ARCHIVO EXISTENTE:\n"
    "<editar_archivo ruta=\"ruta/relativa/archivo.tsx\">\n"
    "<buscar>\n"
    "líneas exactas actuales\n"
    "</buscar>\n"
    "<reemplazar>\n"
    "nuevas líneas\n"
    "</reemplazar>\n"
    "</editar_archivo>\n\n"
    "REGLAS DE EJECUCIÓN RÁPIDA Y AUTÓNOMA:\n"
    "- Sé directo: haz máximo 1 o 2 rondas breves de `buscar_en_codigo`/`leer_archivo` con rangos cortos y pasa de inmediato a emitir `<escribir_archivo>` o `<editar_archivo>`.\n"
    "- Nunca ejecutes comandos de relleno como `echo ok` o `echo skip`; cuando tengas el contexto, emite directamente el bloque XML.\n"
    "- Puedes emitir varios bloques `<escribir_archivo>` y `<editar_archivo>` en la misma respuesta.\n"
    "- Nunca termines diciendo 'Voy a crear/reescribir...' sin incluir el bloque XML real en ese mismo mensaje.\n"
    "- En React usa TypeScript limpio, Tailwind CSS, cero emojis y solo íconos SVG de `lucide-react`.\n"
    "- Protege secretos: nunca muestres `.env`. Responde siempre en español."
)


def _resolver_ruta_segura(ruta_str: str) -> Path:
    p = Path(ruta_str or ".")
    if not p.is_absolute():
        p = (RAIZ_PROYECTO / p).resolve()
    else:
        p = p.resolve()
    return p


def tool_listar_directorio(ruta: str = ".") -> dict:
    try:
        p = _resolver_ruta_segura(ruta)
        if not p.exists():
            return {"error": f"La ruta '{ruta}' no existe."}
        if not p.is_dir():
            return {"error": f"'{ruta}' es un archivo, usa leer_archivo."}
        items = []
        for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.name in {"node_modules", ".git", "__pycache__", ".pytest_cache"}:
                continue
            items.append({
                "nombre": item.name,
                "tipo": "directorio" if item.is_dir() else "archivo",
                "tamano_bytes": item.stat().st_size if item.is_file() else None,
            })
        ruta_rel = str(p.relative_to(RAIZ_PROYECTO)) if p.is_relative_to(RAIZ_PROYECTO) else str(p)
        return {"ruta": ruta_rel, "total": len(items), "items": items[:120]}
    except Exception as e:
        return {"error": str(e)}


def tool_leer_archivo(ruta: str, linea_inicio: int | None = None, linea_fin: int | None = None) -> dict:
    try:
        p = _resolver_ruta_segura(ruta)
        if p.name == ".env":
            return {"error": "Lectura de .env bloqueada por seguridad para proteger credenciales."}
        if not p.exists():
            return {"error": f"El archivo '{ruta}' no existe."}
        if p.is_dir():
            return {"error": f"'{ruta}' es un directorio, usa listar_directorio."}

        texto = p.read_text(encoding="utf-8", errors="replace")
        lineas = texto.splitlines()
        total_lineas = len(lineas)

        ini = max(1, int(linea_inicio)) if linea_inicio is not None else 1
        if linea_fin is not None:
            fin = min(total_lineas, int(linea_fin))
        else:
            # Si no pidió rango explícito y el archivo es largo, devolver primeras 260 líneas para no inflar el prompt
            fin = min(total_lineas, ini + 259)
        if ini > fin and total_lineas > 0:
            ini = 1
            fin = min(total_lineas, 260)

        seleccion = lineas[ini - 1 : fin]
        numeradas = "\n".join(f"{i}: {linea}" for i, linea in enumerate(seleccion, start=ini))
        truncado = fin < total_lineas
        if len(numeradas) > 16000:
            numeradas = numeradas[:16000]
            truncado = True
        if truncado:
            numeradas += (
                f"\n... [Mostrando L{ini}-L{fin} de {total_lineas} líneas totales. "
                "Usa buscar_en_codigo o linea_inicio/linea_fin si requieres otra sección específica.]"
            )

        ruta_rel = str(p.relative_to(RAIZ_PROYECTO)) if p.is_relative_to(RAIZ_PROYECTO) else str(p)
        return {
            "ruta": ruta_rel,
            "total_lineas": total_lineas,
            "rango_leido": f"L{ini}-L{fin}",
            "truncado": truncado,
            "contenido": numeradas,
        }
    except Exception as e:
        return {"error": str(e)}


def tool_escribir_archivo(ruta: str, contenido: str) -> dict:
    try:
        p = _resolver_ruta_segura(ruta)
        if p.name == ".env":
            return {"error": "Modificación de .env bloqueada por seguridad."}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")
        ruta_rel = str(p.relative_to(RAIZ_PROYECTO)) if p.is_relative_to(RAIZ_PROYECTO) else str(p)
        return {
            "exito": True,
            "ruta": ruta_rel,
            "lineas_escritas": len(contenido.splitlines()),
            "bytes_escritos": len(contenido.encode("utf-8")),
        }
    except Exception as e:
        return {"error": str(e)}


def tool_editar_archivo(ruta: str, texto_buscar: str, texto_reemplazar: str) -> dict:
    try:
        p = _resolver_ruta_segura(ruta)
        if p.name == ".env":
            return {"error": "Modificación de .env bloqueada por seguridad."}
        if not p.exists() or not p.is_file():
            return {"error": f"El archivo '{ruta}' no existe."}
        actual = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        buscar_norm = texto_buscar.replace("\r\n", "\n")
        reemplazar_norm = texto_reemplazar.replace("\r\n", "\n")

        if not buscar_norm:
            return {"error": "El bloque <buscar> no puede estar vacío."}

        if buscar_norm in actual:
            ocurrencias = actual.count(buscar_norm)
            nuevo = actual.replace(buscar_norm, reemplazar_norm)
        else:
            # Fallback tolerante a espacios finales por línea en Windows
            lineas_act = [l.rstrip() for l in actual.split("\n")]
            lineas_bus = [l.rstrip() for l in buscar_norm.strip("\n").split("\n")]
            n_bus = len(lineas_bus)
            pos_match = -1
            for i_linea in range(len(lineas_act) - n_bus + 1):
                if lineas_act[i_linea : i_linea + n_bus] == lineas_bus:
                    pos_match = i_linea
                    break
            if pos_match == -1:
                return {
                    "error": (
                        "No se encontró el bloque <buscar> en el archivo. "
                        "Usa leer_archivo con linea_inicio/linea_fin o usa <escribir_archivo> para sobrescribir."
                    )
                }
            lineas_orig = actual.split("\n")
            nuevas_lineas = reemplazar_norm.strip("\n").split("\n")
            nuevo = "\n".join(lineas_orig[:pos_match] + nuevas_lineas + lineas_orig[pos_match + n_bus :])
            ocurrencias = 1

        p.write_text(nuevo, encoding="utf-8")
        ruta_rel = str(p.relative_to(RAIZ_PROYECTO)) if p.is_relative_to(RAIZ_PROYECTO) else str(p)
        return {
            "exito": True,
            "ruta": ruta_rel,
            "reemplazos_aplicados": ocurrencias,
            "total_lineas_actual": len(nuevo.splitlines()),
        }
    except Exception as e:
        return {"error": str(e)}


def tool_buscar_en_codigo(patron: str, ruta: str = ".") -> dict:
    try:
        base = _resolver_ruta_segura(ruta)
        if not base.exists():
            return {"error": f"La ruta '{ruta}' no existe."}
        texto_patron = (patron or "").strip()
        if not texto_patron:
            return {"error": "El patrón de búsqueda no puede estar vacío."}

        try:
            regex = re.compile(texto_patron, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(texto_patron), re.IGNORECASE)

        coincidencias = []
        archivos = [base] if base.is_file() else base.rglob("*")
        for arch in archivos:
            if not arch.is_file():
                continue
            if arch.name in {".env", "package-lock.json"} or any(
                part in DIRS_IGNORADOS_BUSQUEDA for part in arch.parts
            ):
                continue
            if arch.suffix.lower() in {".db", ".mp4", ".jpg", ".jpeg", ".png", ".pyc", ".exe"}:
                continue
            try:
                lineas = arch.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for idx, linea in enumerate(lineas, start=1):
                if regex.search(linea):
                    rel = str(arch.relative_to(RAIZ_PROYECTO)) if arch.is_relative_to(RAIZ_PROYECTO) else str(arch)
                    coincidencias.append({
                        "archivo": rel,
                        "linea": idx,
                        "texto": linea.strip()[:180],
                    })
                    if len(coincidencias) >= 60:
                        return {
                            "patron": patron,
                            "total_encontradas": len(coincidencias),
                            "aviso": "Mostrando las primeras 60 coincidencias.",
                            "coincidencias": coincidencias,
                        }
        return {
            "patron": patron,
            "total_encontradas": len(coincidencias),
            "coincidencias": coincidencias,
        }
    except Exception as e:
        return {"error": str(e)}


def tool_ejecutar_comando(comando: str) -> dict:
    cmd_str = (comando or "").strip()
    if len(cmd_str) > 550 or any(
        kw in cmd_str.lower()
        for kw in ("set-content", "out-file", "writealltext", "@'", '@"')
    ):
        return {
            "error": (
                "No uses ejecutar_comando para escribir o modificar archivos largos. "
                "Usa directamente <escribir_archivo ruta=\"...\">...</escribir_archivo> o <editar_archivo>."
            )
        }
    try:
        resultado = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd_str],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(RAIZ_PROYECTO),
            encoding="utf-8",
            errors="replace",
        )
        stdout = resultado.stdout.strip()
        stderr = resultado.stderr.strip()
        return {
            "comando": cmd_str,
            "codigo_salida": resultado.returncode,
            "stdout": stdout[:10000] if stdout else "",
            "stderr": stderr[:5000] if stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": "El comando superó el tiempo límite de ejecución (90s)."}
    except Exception as e:
        return {"error": str(e)}


MAPA_TOOLS_CHAT = {
    "listar_directorio": tool_listar_directorio,
    "leer_archivo": tool_leer_archivo,
    "escribir_archivo": tool_escribir_archivo,
    "editar_archivo": tool_editar_archivo,
    "buscar_en_codigo": tool_buscar_en_codigo,
    "ejecutar_comando": tool_ejecutar_comando,
}


def _extraer_ruta_parcial_json(raw_args: str) -> str:
    """Extrae el valor de ruta/comando mientras grok-4.7 aún está streameando el JSON."""
    m = re.search(r'"(?:ruta|comando|patron)"\s*:\s*"([^"]+)"', raw_args)
    return m.group(1) if m else ""


def _resumir_resultado_tool(nombre: str, args: dict, resultado: dict) -> tuple[str, str, bool]:
    """Devuelve (resumen_corto, detalle_para_ui, exito) para mostrar en el acordeón de la UI."""
    if "error" in resultado:
        return f"Error: {resultado['error']}", json.dumps(resultado, ensure_ascii=False, indent=2), False

    if nombre == "listar_directorio":
        resumen = f"{resultado.get('total', 0)} elementos en `{resultado.get('ruta', '.')}`"
        nombres = [
            f"{'[DIR] ' if i['tipo'] == 'directorio' else '      '}{i['nombre']}"
            for i in resultado.get("items", [])[:40]
        ]
        return resumen, "\n".join(nombres), True

    if nombre == "leer_archivo":
        resumen = f"Leído `{resultado.get('ruta')}` ({resultado.get('rango_leido')}, {resultado.get('total_lineas')} líneas)"
        vista = (resultado.get("contenido") or "")[:2400]
        return resumen, vista, True

    if nombre == "escribir_archivo":
        resumen = f"Guardado `{resultado.get('ruta')}` ({resultado.get('lineas_escritas')} líneas · {resultado.get('bytes_escritos')} B)"
        return resumen, json.dumps(resultado, ensure_ascii=False, indent=2), True

    if nombre == "editar_archivo":
        resumen = f"Editado `{resultado.get('ruta')}` ({resultado.get('reemplazos_aplicados')} bloque actualizado)"
        return resumen, json.dumps(resultado, ensure_ascii=False, indent=2), True

    if nombre == "buscar_en_codigo":
        resumen = f"{resultado.get('total_encontradas', 0)} coincidencias para \"{args.get('patron', '')}\""
        lineas = [
            f"{c['archivo']}:{c['linea']} -> {c['texto']}"
            for c in resultado.get("coincidencias", [])[:25]
        ]
        return resumen, "\n".join(lineas) if lineas else "Sin coincidencias.", True

    if nombre == "ejecutar_comando":
        rc = resultado.get("codigo_salida", 0)
        resumen = f"Código de salida {rc} · `{args.get('comando', '')}`"
        partes = []
        if resultado.get("stdout"):
            partes.append(resultado["stdout"][:3000])
        if resultado.get("stderr"):
            partes.append(f"[STDERR]\n{resultado['stderr'][:1500]}")
        return resumen, "\n".join(partes) if partes else "(Comando finalizado sin salida en consola)", rc == 0

    return "Completado", json.dumps(resultado, ensure_ascii=False, indent=2), True


def _preparar_db_ui() -> Path:
    """Usa una copia de trabajo de inventario.db en logs/ para no ensuciar git status."""
    config.LOGS_DIR.mkdir(exist_ok=True)
    origen = config.DATA_DIR / "inventario.db"
    if origen.exists() and not UI_DB_PATH.exists():
        shutil.copy2(origen, UI_DB_PATH)
    db_mod.DB_PATH = UI_DB_PATH
    return UI_DB_PATH


async def endpoint_salud(request: Request) -> JSONResponse:
    """Estado del servidor, modelo activo y conexión con SQLite/Catálogo."""
    _preparar_db_ui()
    catalogo = cargar_catalogo()
    conn = sqlite3.connect(db_mod.DB_PATH)
    total_stock = conn.execute("SELECT SUM(stock) FROM inventario").fetchone()[0] or 0
    tiene_tabla_cot = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cotizaciones'"
    ).fetchone()[0]
    cotizaciones_registradas = 0
    if tiene_tabla_cot:
        cotizaciones_registradas = conn.execute("SELECT COUNT(*) FROM cotizaciones").fetchone()[0]
    conn.close()

    return JSONResponse({
        "estado": "online",
        "modelo": config.MODEL,
        "endpoint": "https://api.reto.pltk.mx/v1",
        "herramientas_chat": list(MAPA_TOOLS_CHAT.keys()),
        "total_repuestos_catalogo": len(catalogo),
        "unidades_stock_erp": total_stock,
        "cotizaciones_generadas": cotizaciones_registradas,
    })


async def endpoint_foto_muestra(request: Request):
    """Sirve las imágenes reales de data/fotos_prueba/ para previsualización en la UI."""
    nombre = request.path_params.get("nombre", "")
    ruta = (FOTOS_PRUEBA_DIR / nombre).resolve()
    if not ruta.exists() or ruta.parent != FOTOS_PRUEBA_DIR.resolve():
        return JSONResponse({"error": "Fotografía no encontrada."}, status_code=404)
    return FileResponse(str(ruta), media_type="image/jpeg")


# --- Trabajos de chat desacoplados de la conexión HTTP ---
# El agente sigue corriendo en el servidor aunque el navegador se recargue (HMR de Vite, F5, etc.).
# El cliente guarda el job_id y cuántos eventos procesó, y retoma con GET /api/chat/{job_id}/stream?desde=N.
JOBS_CHAT: dict[str, dict] = {}
TTL_JOB_SEGUNDOS = 1800
HEADERS_SSE = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class _ColaJob:
    """Interfaz mínima compatible con el antiguo asyncio.Queue: put(str) guarda el evento, put(None) cierra."""

    def __init__(self, job: dict):
        self._job = job

    async def put(self, item):
        if item is None:
            self._job["terminado"] = True
        else:
            self._job["eventos"].append(item)


def _podar_jobs() -> None:
    ahora = time.time()
    vencidos = [
        jid
        for jid, j in JOBS_CHAT.items()
        if j.get("terminado") and ahora - j.get("creado", ahora) > TTL_JOB_SEGUNDOS
    ]
    for jid in vencidos:
        JOBS_CHAT.pop(jid, None)


async def _stream_job(job: dict, desde: int = 0):
    """Emite los eventos del trabajo desde el índice `desde` y heartbeats cada 2s mientras espera."""
    idx = max(0, int(desde))
    inactivo = 0.0
    while True:
        if idx < len(job["eventos"]):
            yield job["eventos"][idx]
            idx += 1
            inactivo = 0.0
            continue
        if job["terminado"]:
            break
        await asyncio.sleep(0.05)
        inactivo += 0.05
        if inactivo >= 2.0:
            inactivo = 0.0
            yield ": keepalive\n\n"


async def endpoint_chat_reanudar(request: Request):
    """Retoma el stream de un trabajo en curso (o terminado) desde el evento `desde`."""
    job = JOBS_CHAT.get(request.path_params.get("job_id", ""))
    if job is None:
        return JSONResponse({"error": "Trabajo no encontrado o expirado."}, status_code=404)
    try:
        desde = int(request.query_params.get("desde", "0") or 0)
    except ValueError:
        desde = 0
    return StreamingResponse(_stream_job(job, desde), media_type="text/event-stream", headers=HEADERS_SSE)


async def endpoint_chat_cancelar(request: Request):
    """Cancelación explícita (botón Detener). Cerrar o recargar la pestaña NO cancela."""
    job = JOBS_CHAT.get(request.path_params.get("job_id", ""))
    if job is None:
        return JSONResponse({"error": "Trabajo no encontrado."}, status_code=404)
    tarea = job.get("tarea")
    if tarea is not None and not tarea.done():
        tarea.cancel()
    return JSONResponse({"cancelado": True})


def _clasificar_error_llm(exc: BaseException) -> tuple[bool, bool]:
    """Clasifica errores de OpenAI/xAI/httpx en (reintentable, es_capacidad_o_saturacion).

    Nota crítica: cuando `stream=True`, si xAI satura en mitad del SSE emite un frame
    `data: {"error": {"message": "The model is currently at capacity..."}}` sobre HTTP 200,
    y el SDK de OpenAI lanza `openai.APIError` directo (NO `InternalServerError`).
    """
    texto = str(exc).lower()
    indicadores_capacidad = (
        "at capacity",
        "high demand",
        "overloaded",
        "temporarily unavailable",
        "rate limit",
        "too many requests",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    )
    es_capacidad = any(ind in texto for ind in indicadores_capacidad) or isinstance(
        exc, (openai.InternalServerError, openai.RateLimitError)
    )

    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError)):
        return False, False
    if getattr(exc, "status_code", None) == 402:
        return False, False
    if isinstance(exc, (openai.BadRequestError, openai.UnprocessableEntityError)):
        return es_capacidad, es_capacidad

    if isinstance(
        exc,
        (
            openai.APIError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            httpx.HTTPError,
        ),
    ):
        return True, es_capacidad

    return False, False


async def endpoint_chat(request: Request):
    """Agente conversacional estilo Gemini + chat.py con Heartbeat SSE y progreso en vivo."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Cuerpo JSON inválido."}, status_code=400)

    mensajes_usuario = body.get("mensajes", [])
    usar_tools = bool(body.get("usar_tools", True))

    mensajes = [{"role": "system", "content": SYSTEM_CHAT_AGENTE}]
    total_hist = len(mensajes_usuario)
    for idx_m, m in enumerate(mensajes_usuario):
        rol = m.get("role", "user")
        contenido = str(m.get("content", "")).strip()
        acciones_previas = m.get("acciones_resumen", "")
        acciones_detalle = m.get("acciones_detalle", "")
        if rol == "assistant":
            bloques_ctx = []
            if acciones_previas:
                bloques_ctx.append(f"[Herramientas ya ejecutadas en este turno: {acciones_previas}]")
            # Conservar el contexto real de los últimos 2 turnos para no releer archivos desde cero
            if acciones_detalle and (total_hist - idx_m) <= 4:
                bloques_ctx.append(f"[Extracto de salidas recientes:\n{acciones_detalle[:6000]}]")
            if contenido:
                bloques_ctx.append(contenido)
            contenido = "\n\n".join(bloques_ctx).strip()
        if rol in ("user", "assistant") and contenido:
            mensajes.append({"role": rol, "content": contenido})

    inicio = time.time()
    _podar_jobs()
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    job: dict = {"eventos": [], "terminado": False, "creado": time.time(), "tarea": None}
    JOBS_CHAT[job_id] = job
    cola_sse = _ColaJob(job)
    await cola_sse.put(f"data: {json.dumps({'tipo': 'job', 'job_id': job_id})}\n\n")

    async def _worker_react():
        cliente = None
        pt_total = 0
        ct_total = 0
        alcanzo_limite = True

        try:
            base_url = config.os.getenv("PLATICA_BASE_URL")
            api_key = config.os.getenv("PLATICA_API_KEY")
            if not base_url or not api_key:
                raise RuntimeError("Faltan PLATICA_BASE_URL o PLATICA_API_KEY en .env")

            def _compactar_mensajes_para_llm(historial: list[dict]) -> list[dict]:
                """Mantiene el prompt ágil (<45k chars) en bucles largos sin perder contexto reciente."""
                total_chars = sum(len(str(m.get("content", ""))) for m in historial)
                if total_chars <= 42000 or len(historial) <= 8:
                    return historial
                compactados = []
                limite_recientes = len(historial) - 6
                for idx_h, msg_h in enumerate(historial):
                    if idx_h < 2 or idx_h >= limite_recientes:
                        compactados.append(msg_h)
                        continue
                    rol_h = msg_h.get("role")
                    cont_h = str(msg_h.get("content") or "")
                    if rol_h == "tool" and len(cont_h) > 2200:
                        compactados.append({
                            **msg_h,
                            "content": cont_h[:2200] + "\n... [Salida previa compactada para velocidad]",
                        })
                    else:
                        compactados.append(msg_h)
                return compactados

            def _limpiar_xml_para_historial(texto_bruto: str) -> str:
                """Reemplaza cuerpos enormes ya guardados en disco por un marcador ligero en el historial."""
                limpio = re.sub(
                    r"<escribir_archivo\s+(?:ruta|path|archivo)=[\"']([^\"']+)[\"']\s*>.*?</escribir_archivo>",
                    r"[Archivo guardado en disco: \1]",
                    texto_bruto,
                    flags=re.DOTALL,
                )
                limpio = re.sub(
                    r"<editar_archivo\s+(?:ruta|path|archivo)=[\"']([^\"']+)[\"']\s*>.*?</editar_archivo>",
                    r"[Edición aplicada en disco: \1]",
                    limpio,
                    flags=re.DOTALL,
                )
                return limpio

            cliente = openai.AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=httpx.Timeout(connect=15.0, read=150.0, write=30.0, pool=30.0),
            )

            for iteracion in range(1, MAX_ITERACIONES_CHAT + 1):
                mensajes_envio = _compactar_mensajes_para_llm(mensajes)
                kwargs_llm = {
                    "model": config.MODEL,
                    "messages": mensajes_envio,
                    "reasoning_effort": "minimal",
                    "stream": True,
                }
                if usar_tools:
                    kwargs_llm["tools"] = TOOLS_CHAT_AGENTE
                    kwargs_llm["tool_choice"] = "auto"

                texto_iteracion: list[str] = []
                tool_calls_acum: dict[int, dict] = {}
                archivos_xml_guardados: list[tuple[str, str, dict]] = []
                pt_iter = None
                ct_iter = None
                finish_reason = None

                # Reintento automático ante saturación de xAI ("at capacity" en HTTP o mitad de SSE) y red
                ultimo_err_stream = None
                contador_xml = 0
                max_intentos_cap = 6
                max_intentos_red = 4
                for intento_llm in range(1, max_intentos_cap + 1):
                    texto_iteracion = []
                    tool_calls_acum = {}
                    archivos_xml_guardados = []
                    pt_iter = None
                    ct_iter = None
                    finish_reason = None
                    emitio_algo = False

                    buffer_visible = ""
                    xml_activo: dict | None = None
                    stream = None

                    try:
                        stream = await cliente.chat.completions.create(**kwargs_llm)
                        async for chunk in stream:
                            if getattr(chunk, "usage", None):
                                pt_iter = getattr(chunk.usage, "prompt_tokens", None)
                                ct_iter = getattr(chunk.usage, "completion_tokens", None)

                            if not chunk.choices:
                                continue
                            choice = chunk.choices[0]
                            if getattr(choice, "finish_reason", None):
                                finish_reason = choice.finish_reason

                            delta = choice.delta
                            if not delta:
                                continue

                            if delta.content:
                                texto_iteracion.append(delta.content)
                                buffer_visible += delta.content

                                # Procesar <escribir_archivo> y <editar_archivo> en streaming directo sin búfer
                                while buffer_visible:
                                    if xml_activo is None:
                                        pos_lt = buffer_visible.find("<")
                                        if pos_lt == -1:
                                            payload_tok = json.dumps(
                                                {"tipo": "token", "contenido": buffer_visible},
                                                ensure_ascii=False,
                                            )
                                            await cola_sse.put(f"data: {payload_tok}\n\n")
                                            emitio_algo = True
                                            buffer_visible = ""
                                            break

                                        if pos_lt > 0:
                                            antes = buffer_visible[:pos_lt]
                                            payload_tok = json.dumps(
                                                {"tipo": "token", "contenido": antes},
                                                ensure_ascii=False,
                                            )
                                            await cola_sse.put(f"data: {payload_tok}\n\n")
                                            emitio_algo = True
                                            buffer_visible = buffer_visible[pos_lt:]

                                        # Ahora buffer_visible empieza con '<'
                                        prefijos_xml = ("<escribir_archivo", "<editar_archivo")
                                        es_posible_xml = any(
                                            p.startswith(buffer_visible) or buffer_visible.startswith(p)
                                            for p in prefijos_xml
                                        )
                                        if not es_posible_xml:
                                            payload_tok = json.dumps(
                                                {"tipo": "token", "contenido": "<"},
                                                ensure_ascii=False,
                                            )
                                            await cola_sse.put(f"data: {payload_tok}\n\n")
                                            emitio_algo = True
                                            buffer_visible = buffer_visible[1:]
                                            continue

                                        pos_gt = buffer_visible.find(">")
                                        if pos_gt == -1:
                                            if len(buffer_visible) > 260:
                                                payload_tok = json.dumps(
                                                    {"tipo": "token", "contenido": buffer_visible},
                                                    ensure_ascii=False,
                                                )
                                                await cola_sse.put(f"data: {payload_tok}\n\n")
                                                emitio_algo = True
                                                buffer_visible = ""
                                            break

                                        tag_apertura = buffer_visible[: pos_gt + 1]
                                        m_tag = re.match(
                                            r'^<(escribir_archivo|editar_archivo)\s+(?:ruta|path|archivo)=["\']([^"\']+)["\']\s*>$',
                                            tag_apertura.strip(),
                                        )
                                        if not m_tag:
                                            payload_tok = json.dumps(
                                                {"tipo": "token", "contenido": tag_apertura},
                                                ensure_ascii=False,
                                            )
                                            await cola_sse.put(f"data: {payload_tok}\n\n")
                                            emitio_algo = True
                                            buffer_visible = buffer_visible[pos_gt + 1 :]
                                            continue

                                        contador_xml += 1
                                        herramienta_xml = m_tag.group(1)
                                        ruta_xml = m_tag.group(2).strip()
                                        xml_id = f"xml_{herramienta_xml}_{iteracion}_{contador_xml}"
                                        xml_activo = {
                                            "id": xml_id,
                                            "herramienta": herramienta_xml,
                                            "ruta": ruta_xml,
                                            "contenido": "",
                                            "ultimo_reporte": 0,
                                            "t0": time.time(),
                                        }
                                        buffer_visible = buffer_visible[pos_gt + 1 :]
                                        emitio_algo = True
                                        ev_ini_xml = {
                                            "tipo": "tool_inicio",
                                            "id": xml_id,
                                            "iteracion": iteracion,
                                            "herramienta": herramienta_xml,
                                            "argumentos": {"ruta": ruta_xml},
                                        }
                                        await cola_sse.put(
                                            f"data: {json.dumps(ev_ini_xml, ensure_ascii=False)}\n\n"
                                        )
                                    else:
                                        tag_cierre = f"</{xml_activo['herramienta']}>"
                                        xml_activo["contenido"] += buffer_visible
                                        buffer_visible = ""
                                        pos_cierre = xml_activo["contenido"].find(tag_cierre)
                                        if pos_cierre == -1:
                                            largo_c = len(xml_activo["contenido"])
                                            if largo_c - xml_activo["ultimo_reporte"] >= 400:
                                                xml_activo["ultimo_reporte"] = largo_c
                                                ev_prog_xml = {
                                                    "tipo": "tool_progreso",
                                                    "id": xml_activo["id"],
                                                    "herramienta": xml_activo["herramienta"],
                                                    "caracteres": largo_c,
                                                    "ruta_parcial": xml_activo["ruta"],
                                                }
                                                await cola_sse.put(
                                                    f"data: {json.dumps(ev_prog_xml, ensure_ascii=False)}\n\n"
                                                )
                                            break

                                        cuerpo_bruto = xml_activo["contenido"][:pos_cierre]
                                        resto_post = xml_activo["contenido"][pos_cierre + len(tag_cierre) :]
                                        h_nombre = xml_activo["herramienta"]

                                        if h_nombre == "escribir_archivo":
                                            codigo_limpio = cuerpo_bruto.lstrip("\r\n")
                                            if codigo_limpio.startswith("```"):
                                                codigo_limpio = codigo_limpio.split("\n", 1)[-1]
                                                if codigo_limpio.rstrip().endswith("```"):
                                                    codigo_limpio = codigo_limpio.rstrip()[:-3].rstrip() + "\n"
                                            res_xml = await asyncio.to_thread(
                                                tool_escribir_archivo, xml_activo["ruta"], codigo_limpio
                                            )
                                        else:
                                            m_bus = re.search(
                                                r"<buscar>\r?\n?(.*?)\r?\n?</buscar>",
                                                cuerpo_bruto,
                                                flags=re.DOTALL,
                                            )
                                            m_rem = re.search(
                                                r"<reemplazar>\r?\n?(.*?)\r?\n?</reemplazar>",
                                                cuerpo_bruto,
                                                flags=re.DOTALL,
                                            )
                                            if not m_bus or m_rem is None:
                                                res_xml = {
                                                    "error": (
                                                        "Formato <editar_archivo> incompleto: debe incluir "
                                                        "<buscar>...</buscar> y <reemplazar>...</reemplazar>."
                                                    )
                                                }
                                            else:
                                                res_xml = await asyncio.to_thread(
                                                    tool_editar_archivo,
                                                    xml_activo["ruta"],
                                                    m_bus.group(1),
                                                    m_rem.group(1),
                                                )

                                        dur_xml = round((time.time() - xml_activo["t0"]) * 1000)
                                        resumen_ui, detalle_ui, exito_xml = _resumir_resultado_tool(
                                            h_nombre,
                                            {"ruta": xml_activo["ruta"]},
                                            res_xml,
                                        )
                                        ev_fin_xml = {
                                            "tipo": "tool_fin",
                                            "id": xml_activo["id"],
                                            "iteracion": iteracion,
                                            "herramienta": h_nombre,
                                            "argumentos": {"ruta": xml_activo["ruta"]},
                                            "resumen": resumen_ui,
                                            "detalle": detalle_ui,
                                            "exito": exito_xml,
                                            "duracion_ms": dur_xml,
                                        }
                                        await cola_sse.put(
                                            f"data: {json.dumps(ev_fin_xml, ensure_ascii=False)}\n\n"
                                        )
                                        archivos_xml_guardados.append((h_nombre, xml_activo["ruta"], res_xml))
                                        xml_activo = None
                                        buffer_visible = resto_post

                            if getattr(delta, "tool_calls", None):
                                for tc in delta.tool_calls:
                                    idx = getattr(tc, "index", 0) or 0
                                    if idx not in tool_calls_acum:
                                        tool_calls_acum[idx] = {
                                            "id": getattr(tc, "id", None) or f"call_{iteracion}_{intento_llm}_{idx}",
                                            "name": "",
                                            "arguments": "",
                                            "anunciado": False,
                                            "ultimo_reporte_chars": 0,
                                        }
                                    entry = tool_calls_acum[idx]
                                    if getattr(tc, "id", None):
                                        entry["id"] = tc.id
                                    if getattr(tc, "function", None):
                                        if tc.function.name:
                                            entry["name"] += tc.function.name
                                        if tc.function.arguments:
                                            entry["arguments"] += tc.function.arguments

                                    if entry["name"] and not entry["anunciado"]:
                                        entry["anunciado"] = True
                                        emitio_algo = True
                                        ev_ini_temprano = {
                                            "tipo": "tool_inicio",
                                            "id": entry["id"],
                                            "iteracion": iteracion,
                                            "herramienta": entry["name"],
                                            "argumentos": {"estado": "generando argumentos..."},
                                        }
                                        await cola_sse.put(
                                            f"data: {json.dumps(ev_ini_temprano, ensure_ascii=False)}\n\n"
                                        )

                                    largo_actual = len(entry["arguments"])
                                    if (
                                        entry["anunciado"]
                                        and largo_actual - entry["ultimo_reporte_chars"] >= 500
                                    ):
                                        entry["ultimo_reporte_chars"] = largo_actual
                                        ruta_parcial = _extraer_ruta_parcial_json(entry["arguments"])
                                        ev_prog = {
                                            "tipo": "tool_progreso",
                                            "id": entry["id"],
                                            "herramienta": entry["name"],
                                            "caracteres": largo_actual,
                                            "ruta_parcial": ruta_parcial,
                                        }
                                        await cola_sse.put(
                                            f"data: {json.dumps(ev_prog, ensure_ascii=False)}\n\n"
                                        )

                        if xml_activo is None and buffer_visible:
                            payload_tok = json.dumps(
                                {"tipo": "token", "contenido": buffer_visible},
                                ensure_ascii=False,
                            )
                            await cola_sse.put(f"data: {payload_tok}\n\n")
                            buffer_visible = ""

                        ultimo_err_stream = None
                        break
                    except (
                        openai.APIError,
                        openai.APIConnectionError,
                        openai.APITimeoutError,
                        httpx.HTTPError,
                    ) as e_red:
                        ultimo_err_stream = e_red
                        reintentable, es_capacidad = _clasificar_error_llm(e_red)

                        # Cerrar limpiamente tarjetas de herramientas abiertas en la UI si el corte ocurrió a mitad de stream
                        if xml_activo is not None:
                            dur_corte = round((time.time() - xml_activo["t0"]) * 1000)
                            ev_cierre_xml = {
                                "tipo": "tool_fin",
                                "id": xml_activo["id"],
                                "iteracion": iteracion,
                                "herramienta": xml_activo["herramienta"],
                                "argumentos": {"ruta": xml_activo["ruta"]},
                                "resumen": "Interrumpido por saturación en xAI (reintentando...)",
                                "detalle": str(e_red),
                                "exito": False,
                                "duracion_ms": dur_corte,
                            }
                            await cola_sse.put(
                                f"data: {json.dumps(ev_cierre_xml, ensure_ascii=False)}\n\n"
                            )
                            xml_activo = None

                        for entry_abierta in tool_calls_acum.values():
                            if entry_abierta.get("anunciado"):
                                ev_cierre_tc = {
                                    "tipo": "tool_fin",
                                    "id": entry_abierta["id"],
                                    "iteracion": iteracion,
                                    "herramienta": entry_abierta["name"] or "herramienta",
                                    "argumentos": {},
                                    "resumen": "Interrumpido por saturación en xAI (reintentando...)",
                                    "detalle": str(e_red),
                                    "exito": False,
                                    "duracion_ms": 0,
                                }
                                await cola_sse.put(
                                    f"data: {json.dumps(ev_cierre_tc, ensure_ascii=False)}\n\n"
                                )

                        if not reintentable:
                            raise

                        # Si ya había guardado algún bloque XML previo en esta iteración antes del corte, conservar el avance
                        if archivos_xml_guardados:
                            tool_calls_acum = {}
                            ultimo_err_stream = None
                            aviso_parcial = (
                                "\n\n*(xAI reportó alta demanda tras guardar cambios en disco; "
                                "retomando en el siguiente paso...)*\n\n"
                            )
                            await cola_sse.put(
                                f"data: {json.dumps({'tipo': 'token', 'contenido': aviso_parcial}, ensure_ascii=False)}\n\n"
                            )
                            break

                        max_intentos = max_intentos_cap if es_capacidad else max_intentos_red
                        if intento_llm < max_intentos:
                            tabla_espera = (4, 8, 14, 22, 30) if es_capacidad else (2, 5, 9)
                            espera_base = tabla_espera[min(intento_llm - 1, len(tabla_espera) - 1)]
                            espera_s = round(espera_base + random.uniform(0.2, 1.2), 1)
                            motivo_retry = "xAI con alta demanda" if es_capacidad else "reconectando"
                            aviso_retry = (
                                f"\n\n*({motivo_retry}, reintento {intento_llm + 1}/{max_intentos} "
                                f"en {espera_base}s...)*\n\n"
                            )
                            await cola_sse.put(
                                f"data: {json.dumps({'tipo': 'token', 'contenido': aviso_retry}, ensure_ascii=False)}\n\n"
                            )
                            await asyncio.sleep(espera_s)
                            continue
                        raise
                    finally:
                        if stream is not None:
                            try:
                                await stream.close()
                            except Exception:
                                pass

                if ultimo_err_stream is not None:
                    raise ultimo_err_stream

                texto_unido = "".join(texto_iteracion)
                texto_para_hist = _limpiar_xml_para_historial(texto_unido)
                if pt_iter is not None and ct_iter is not None:
                    pt_total += pt_iter
                    ct_total += ct_iter
                else:
                    pt_total += max(20, sum(len(str(m.get("content", ""))) // 4 for m in mensajes_envio) + 60)
                    ct_total += max(
                        8,
                        (len(texto_unido) + sum(len(v["arguments"]) for v in tool_calls_acum.values()))
                        // 4,
                    )

                # Si ejecutó acciones XML (<escribir_archivo> / <editar_archivo>) y no hubo tool_calls JSON
                if archivos_xml_guardados and not tool_calls_acum:
                    detalles_sis = []
                    for h_nom, r_xml, res_x in archivos_xml_guardados:
                        if "error" in res_x:
                            detalles_sis.append(f"{h_nom}({r_xml}) -> ERROR: {res_x['error']}")
                        elif h_nom == "escribir_archivo":
                            detalles_sis.append(
                                f"escribir_archivo({r_xml}) -> OK ({res_x.get('lineas_escritas', 0)} líneas)"
                            )
                        else:
                            detalles_sis.append(
                                f"editar_archivo({r_xml}) -> OK ({res_x.get('reemplazos_aplicados', 1)} reemplazo)"
                            )
                    mensajes.append({"role": "assistant", "content": texto_para_hist})
                    mensajes.append({
                        "role": "user",
                        "content": (
                            f"[SISTEMA: Resultado en disco: {'; '.join(detalles_sis)}. "
                            "Si falta algún paso pedido por el usuario (como editar otro archivo o ejecutar un comando de verificación), "
                            "hazlo ahora. Si ya cumpliste todo lo solicitado, responde con un resumen breve sin repetir bloques XML.]"
                        ),
                    })
                    if texto_unido and not texto_unido.endswith("\n\n"):
                        await cola_sse.put(
                            f"data: {json.dumps({'tipo': 'token', 'contenido': '\n\n'}, ensure_ascii=False)}\n\n"
                        )
                    continue

                # Si no invocó herramientas ni bloques XML, terminó su turno
                if not tool_calls_acum:
                    alcanzo_limite = False
                    break

                if texto_unido and not texto_unido.endswith("\n\n"):
                    await cola_sse.put(
                        f"data: {json.dumps({'tipo': 'token', 'contenido': '\n\n'}, ensure_ascii=False)}\n\n"
                    )

                lista_tool_calls = [tool_calls_acum[k] for k in sorted(tool_calls_acum.keys())]
                mensajes.append({
                    "role": "assistant",
                    "content": texto_para_hist or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"] or "{}",
                            },
                        }
                        for tc in lista_tool_calls
                    ],
                })

                # Ejecutar cada herramienta real en disco / terminal
                for tc in lista_tool_calls:
                    nombre = tc["name"]
                    raw_args = tc["arguments"] or "{}"
                    json_valido = True
                    try:
                        args = json.loads(raw_args)
                        if not isinstance(args, dict):
                            args = {}
                    except json.JSONDecodeError as err_json:
                        json_valido = False
                        args = {"ruta": _extraer_ruta_parcial_json(raw_args) or "JSON truncado"}
                        resultado_tool = {
                            "error": (
                                f"Los argumentos JSON de `{nombre}` llegaron incompletos "
                                f"(finish_reason={finish_reason}, detalle={err_json}). "
                                "Vuelve a llamar la herramienta con un archivo más modular/conciso."
                            )
                        }

                    t_tool = time.time()
                    if json_valido:
                        funcion = MAPA_TOOLS_CHAT.get(nombre)
                        if funcion is None:
                            resultado_tool = {"error": f"Herramienta desconocida: {nombre}"}
                        else:
                            try:
                                resultado_tool = await asyncio.to_thread(funcion, **args)
                            except TypeError as e:
                                resultado_tool = {"error": f"Argumentos inválidos para {nombre}: {e}"}
                            except Exception as e:
                                resultado_tool = {"error": str(e)}

                    duracion_ms = round((time.time() - t_tool) * 1000)
                    resumen_ui, detalle_ui, exito_tool = _resumir_resultado_tool(
                        nombre, args, resultado_tool
                    )

                    # Para no inflar la sesión en localStorage con contenido enorme de escribir_archivo
                    args_ligeros = {
                        k: (f"[{len(str(v))} chars]" if k in ("contenido", "texto_buscar", "texto_reemplazar") and len(str(v)) > 140 else v)
                        for k, v in args.items()
                    }

                    ev_fin = {
                        "tipo": "tool_fin",
                        "id": tc["id"],
                        "iteracion": iteracion,
                        "herramienta": nombre,
                        "argumentos": args_ligeros,
                        "resumen": resumen_ui,
                        "detalle": detalle_ui,
                        "exito": exito_tool,
                        "duracion_ms": duracion_ms,
                    }
                    await cola_sse.put(f"data: {json.dumps(ev_fin, ensure_ascii=False)}\n\n")

                    mensajes.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": nombre,
                        "content": json.dumps(resultado_tool, ensure_ascii=False),
                    })

            if alcanzo_limite:
                aviso_lim = (
                    "\n\n> **Nota del sistema:** Se alcanzó el límite de 16 iteraciones de herramientas en este turno. "
                    "Escribe **\"continúa\"** para que el agente retome exactamente desde este punto."
                )
                await cola_sse.put(
                    f"data: {json.dumps({'tipo': 'token', 'contenido': aviso_lim}, ensure_ascii=False)}\n\n"
                )

            costo = calcular_costo_tokens(pt_total, ct_total)
            meta = {
                "tipo": "fin",
                "modelo": config.MODEL,
                "latencia_segundos": round(time.time() - inicio, 2),
                "usage": {
                    "prompt_tokens": pt_total,
                    "completion_tokens": ct_total,
                    "total_tokens": pt_total + ct_total,
                    "costo_usd": costo["total_usd"],
                },
            }
            await cola_sse.put(f"data: {json.dumps(meta, ensure_ascii=False)}\n\n")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            err_payload = json.dumps({"tipo": "error", "error": str(e)}, ensure_ascii=False)
            await cola_sse.put(f"data: {err_payload}\n\n")
        finally:
            if cliente is not None:
                try:
                    await cliente.close()
                except Exception:
                    pass
            await cola_sse.put(None)

    # La tarea vive en el servidor: NO se cancela si el navegador se desconecta o recarga.
    job["tarea"] = asyncio.create_task(_worker_react())
    return StreamingResponse(_stream_job(job, 0), media_type="text/event-stream", headers=HEADERS_SSE)


class _CompletionsDiagnosticarUI:
    """Optimiza latencia (reasoning_effort='minimal', timeout=65s) y permite simular HTTP 429 en vivo."""

    def __init__(self, real_completions, simular_429: bool = False):
        self._real = real_completions
        self._simular_429 = simular_429
        self.intentos = 0

    async def create(self, *args, **kwargs):
        self.intentos += 1
        if self._simular_429 and self.intentos == 1:
            req = httpx.Request("POST", "https://api.reto.pltk.mx/v1/chat/completions")
            resp = httpx.Response(status_code=429, request=req)
            raise openai.RateLimitError(
                message="429 Too Many Requests: límite de tasa simulado desde Platica AI Studio.",
                response=resp,
                body={"error": {"message": "Rate limit exceeded"}},
            )
        kwargs.setdefault("reasoning_effort", "minimal")
        if kwargs.get("timeout") == 30.0:
            kwargs["timeout"] = 65.0

        # Absorbe picos transitorios 5xx / "model at capacity" de xAI sin alterar agent.py
        for intento_cap, espera_cap in enumerate((4, 8, 14, 0), start=1):
            try:
                return await self._real.create(*args, **kwargs)
            except (openai.RateLimitError, openai.APITimeoutError):
                raise
            except (openai.APIError, httpx.HTTPError) as e_cap:
                reintentable, es_cap = _clasificar_error_llm(e_cap)
                if not reintentable or not es_cap or espera_cap == 0:
                    raise
                await asyncio.sleep(espera_cap + random.uniform(0.2, 1.0))


class _ClienteDiagnosticarUI:
    def __init__(self, cliente_real, simular_429: bool = False):
        self.chat = type(
            "ChatProxy",
            (),
            {"completions": _CompletionsDiagnosticarUI(cliente_real.chat.completions, simular_429)},
        )()


async def endpoint_diagnosticar(request: Request) -> JSONResponse:
    """Ejecuta el agente multimodal real recibiendo 1 o 2 fotografías."""
    _preparar_db_ui()
    content_type = request.headers.get("content-type", "")
    archivos_temp = []
    cliente_real = None

    try:
        simular_429 = False
        ruta_1 = None
        ruta_2 = None

        if "multipart/form-data" in content_type:
            form = await request.form()
            simular_429 = str(form.get("simular_429", "false")).lower() == "true"
            muestra_1 = form.get("muestra_1")
            muestra_2 = form.get("muestra_2")
            foto_1 = form.get("foto_1")
            foto_2 = form.get("foto_2")

            if foto_1 and hasattr(foto_1, "read"):
                contenido_1 = await foto_1.read()
                ruta_1 = _guardar_foto_subida(contenido_1, "foto_1")
            elif muestra_1 and isinstance(muestra_1, str) and muestra_1.strip():
                ruta_1 = FOTOS_PRUEBA_DIR / muestra_1.strip()

            if foto_2 and hasattr(foto_2, "read"):
                contenido_2 = await foto_2.read()
                ruta_2 = _guardar_foto_subida(contenido_2, "foto_2")
            elif muestra_2 and isinstance(muestra_2, str) and muestra_2.strip():
                ruta_2 = FOTOS_PRUEBA_DIR / muestra_2.strip()
        else:
            body = await request.json()
            simular_429 = bool(body.get("simular_429", False))
            m1 = body.get("muestra_1", "test2.jpg")
            m2 = body.get("muestra_2")
            ruta_1 = FOTOS_PRUEBA_DIR / m1
            if m2:
                ruta_2 = FOTOS_PRUEBA_DIR / m2

        if not ruta_1 or not ruta_1.exists():
            return JSONResponse(
                {"error": "Debe proporcionar al menos la primera fotografía."},
                status_code=400,
            )

        cliente_real = config.crear_cliente()
        cliente = _ClienteDiagnosticarUI(cliente_real, simular_429=simular_429)

        resultado = await ejecutar_agente(
            str(ruta_1),
            str(ruta_2) if (ruta_2 and ruta_2.exists()) else None,
            cliente=cliente,
        )
        if isinstance(resultado, dict):
            guardadas = []
            for ruta in (ruta_1, ruta_2):
                if ruta and FOTOS_SUBIDAS_DIR in ruta.parents:
                    guardadas.append(str(ruta.relative_to(RAIZ_PROYECTO)).replace("\\", "/"))
            resultado = {**resultado, "fotos_guardadas": guardadas}
            _registrar_vinculo_fotos(resultado.get("tarea_id"), guardadas)
        return JSONResponse(resultado)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        if cliente_real is not None:
            try:
                await cliente_real.close()
            except Exception:
                pass
        for tmp in archivos_temp:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


async def endpoint_metricas(request: Request) -> JSONResponse:
    """Devuelve catálogo + inventario SQLite + métricas de Semana 3 y Semana 4."""
    _preparar_db_ui()
    catalogo = cargar_catalogo()
    conn = sqlite3.connect(db_mod.DB_PATH)
    conn.row_factory = sqlite3.Row
    filas_inv = {
        r["id_repuesto"]: dict(r)
        for r in conn.execute(
            "SELECT id_repuesto, precio_unitario, stock, ubicacion FROM inventario"
        ).fetchall()
    }
    conn.close()

    repuestos = []
    for item in catalogo:
        inv = filas_inv.get(item["id_repuesto"], {})
        repuestos.append({
            **item,
            "precio_unitario": inv.get("precio_unitario", 0.0),
            "stock": inv.get("stock", 0),
            "ubicacion": inv.get("ubicacion", "N/A"),
        })

    resumen_s4 = {}
    ruta_s4 = config.RESULTADOS_DIR / "resumen_s4.json"
    if ruta_s4.exists():
        resumen_s4 = json.loads(ruta_s4.read_text(encoding="utf-8"))

    evaluacion_s3 = {}
    ruta_s3 = config.RESULTADOS_DIR / "evaluacion_s3.json"
    if ruta_s3.exists():
        evaluacion_s3 = json.loads(ruta_s3.read_text(encoding="utf-8")).get("resumen_metricas", {})

    return JSONResponse({
        "repuestos": repuestos,
        "resumen_s4": resumen_s4,
        "evaluacion_s3": evaluacion_s3,
    })


routes = [
    Route("/api/salud", endpoint_salud, methods=["GET"]),
    Route("/api/fotos-muestra/{nombre}", endpoint_foto_muestra, methods=["GET"]),
    Route("/api/chat", endpoint_chat, methods=["POST"]),
    Route("/api/chat/{job_id}/stream", endpoint_chat_reanudar, methods=["GET"]),
    Route("/api/chat/{job_id}/cancel", endpoint_chat_cancelar, methods=["POST"]),
    Route("/api/diagnosticar", endpoint_diagnosticar, methods=["POST"]),
    Route("/api/metricas", endpoint_metricas, methods=["GET"]),
]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(debug=False, routes=routes, middleware=middleware)

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Iniciando servidor Platica AI Studio API en http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, timeout_graceful_shutdown=2)
