"""Servidor API Asíncrono (Starlette + Uvicorn) para Platica AI Studio (v2.0).

Conecta el Frontend web con:
1. Agente Autónomo de Ingeniería de Software estilo Gemini / chat.py con Streaming SSE
   y herramientas reales:
   - listar_directorio: explorar carpetas y archivos del workspace
   - leer_archivo: leer código completo o por rango exacto de líneas
   - escribir_archivo: crear archivos nuevos o sobrescribirlos
   - editar_archivo: modificar fragmentos exactos de código sin reescribir todo el archivo
   - buscar_en_codigo: buscar funciones, clases o texto en el repositorio
   - ejecutar_comando: ejecutar comandos reales en PowerShell (pytest, git, python, etc.)
2. Agente autónomo multimodal de refacciones (ejecutar_agente + 3 tools reales).
3. Telemetría FinOps, catálogo OEM e inventario SQLite en tiempo real.
"""
import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
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
UI_DB_PATH = config.LOGS_DIR / "inventario_ui.db"
MAX_ITERACIONES_CHAT = 8

DIRS_IGNORADOS_BUSQUEDA = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    ".venv",
    "venv",
}

# --- 1. ESQUEMAS DE HERRAMIENTAS DEL CHAT AGÉNTICO (Evolución de scripts/chat.py) ---
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
            "description": "Lee el contenido de un archivo de código o texto, completo o por rango de líneas.",
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
            "name": "escribir_archivo",
            "description": "Crea un archivo nuevo o sobrescribe su contenido completo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta relativa o absoluta del archivo a crear o sobrescribir.",
                    },
                    "contenido": {
                        "type": "string",
                        "description": "Contenido completo a guardar en el archivo.",
                    },
                },
                "required": ["ruta", "contenido"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editar_archivo",
            "description": "Reemplaza un bloque exacto de texto o código dentro de un archivo existente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta del archivo existente que se desea editar.",
                    },
                    "texto_buscar": {
                        "type": "string",
                        "description": "Fragmento exacto actual en el archivo (incluyendo sangría).",
                    },
                    "texto_reemplazar": {
                        "type": "string",
                        "description": "Nuevo fragmento que reemplazará al anterior.",
                    },
                },
                "required": ["ruta", "texto_buscar", "texto_reemplazar"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_codigo",
            "description": "Busca un texto, función o clase en los archivos del proyecto y devuelve rutas y líneas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patron": {
                        "type": "string",
                        "description": "Texto o identificador a buscar (insensible a mayúsculas).",
                    },
                    "ruta": {
                        "type": "string",
                        "description": "Subcarpeta opcional donde limitar la búsqueda. Por defecto '.'.",
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
            "description": "Ejecuta un comando real en la terminal PowerShell en la raíz del proyecto y devuelve stdout, stderr y código de salida.",
            "parameters": {
                "type": "object",
                "properties": {
                    "comando": {
                        "type": "string",
                        "description": "Comando de PowerShell a ejecutar (ej. 'python -m pytest -q', 'git status', etc.).",
                    }
                },
                "required": ["comando"],
            },
        },
    },
]

SYSTEM_CHAT_AGENTE = (
    "Eres Platica AI Studio (impulsado por grok-4.7), un Agente Autónomo de Ingeniería de Software "
    "e Inteligencia Artificial ejecutándose en el workspace local del usuario en Windows.\n"
    "Cuentas con herramientas reales conectadas a su proyecto:\n"
    "- `listar_directorio`: explora carpetas y archivos.\n"
    "- `leer_archivo`: lee archivos completos o rangos de líneas numeradas.\n"
    "- `escribir_archivo`: crea archivos nuevos o reemplaza su contenido.\n"
    "- `editar_archivo`: hace cambios quirúrgicos de código buscando y reemplazando bloques exactos.\n"
    "- `buscar_en_codigo`: localiza funciones, variables o cadenas en todo el repositorio.\n"
    "- `ejecutar_comando`: corre comandos reales en PowerShell (tests, scripts, git, etc.).\n\n"
    "REGLAS DE CONDUCTA:\n"
    "1. Sé proactivo y resolutivo: si te piden revisar archivos, explicar código del proyecto, editar algo "
    "o correr pruebas, USA tus herramientas reales antes de responder; nunca adivines el contenido de un archivo.\n"
    "2. Antes de modificar un archivo existente con `editar_archivo`, léelo primero con `leer_archivo` para ver el código exacto.\n"
    "3. Protege secretos: nunca muestres el valor de claves privadas dentro de `.env`.\n"
    "4. Responde siempre en español con formato Markdown claro, limpio y estructurado."
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
        fin = min(total_lineas, int(linea_fin)) if linea_fin is not None else total_lineas
        if ini > fin and total_lineas > 0:
            ini = 1

        seleccion = lineas[ini - 1 : fin]
        numeradas = "\n".join(f"{i}: {linea}" for i, linea in enumerate(seleccion, start=ini))
        truncado = False
        if len(numeradas) > 24000:
            numeradas = numeradas[:24000] + "\n... [Contenido truncado a 24,000 caracteres]"
            truncado = True

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
        actual = p.read_text(encoding="utf-8", errors="replace")
        if texto_buscar not in actual:
            return {
                "error": "No se encontró `texto_buscar` exactamente en el archivo. Léelo con `leer_archivo` para verificar sangría y líneas."
            }
        ocurrencias = actual.count(texto_buscar)
        nuevo = actual.replace(texto_buscar, texto_reemplazar)
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
        aguja = patron.lower().strip()
        if not aguja:
            return {"error": "El patrón de búsqueda no puede estar vacío."}

        coincidencias = []
        archivos = [base] if base.is_file() else base.rglob("*")
        for arch in archivos:
            if not arch.is_file():
                continue
            if arch.name == ".env" or any(part in DIRS_IGNORADOS_BUSQUEDA for part in arch.parts):
                continue
            if arch.suffix.lower() in {".db", ".mp4", ".jpg", ".jpeg", ".png", ".pyc", ".exe"}:
                continue
            try:
                lineas = arch.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for idx, linea in enumerate(lineas, start=1):
                if aguja in linea.lower():
                    rel = str(arch.relative_to(RAIZ_PROYECTO)) if arch.is_relative_to(RAIZ_PROYECTO) else str(arch)
                    coincidencias.append({
                        "archivo": rel,
                        "linea": idx,
                        "texto": linea.strip()[:180],
                    })
                    if len(coincidencias) >= 50:
                        return {
                            "patron": patron,
                            "total_encontradas": len(coincidencias),
                            "aviso": "Mostrando las primeras 50 coincidencias.",
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
    try:
        resultado = subprocess.run(
            comando,
            shell=True,
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(RAIZ_PROYECTO),
            encoding="utf-8",
            errors="replace",
        )
        stdout = resultado.stdout.strip()
        stderr = resultado.stderr.strip()
        return {
            "comando": comando,
            "codigo_salida": resultado.returncode,
            "stdout": stdout[:12000] if stdout else "",
            "stderr": stderr[:6000] if stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": "El comando superó el tiempo límite de ejecución (45s)."}
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


def _resumir_resultado_tool(nombre: str, args: dict, resultado: dict) -> tuple[str, str, bool]:
    """Devuelve (resumen_corto, detalle_para_ui, exito) para mostrar en el acordeón de la UI."""
    if "error" in resultado:
        return f"Error: {resultado['error']}", json.dumps(resultado, ensure_ascii=False, indent=2), False

    if nombre == "listar_directorio":
        resumen = f"{resultado.get('total', 0)} elementos en `{resultado.get('ruta', '.')}`"
        nombres = [
            f"{'[DIR] ' if i['tipo'] == 'directorio' else '      '}{i['nombre']}"
            for i in resultado.get("items", [])[:35]
        ]
        return resumen, "\n".join(nombres), True

    if nombre == "leer_archivo":
        resumen = f"Leído `{resultado.get('ruta')}` ({resultado.get('rango_leido')}, {resultado.get('total_lineas')} líneas)"
        vista = (resultado.get("contenido") or "")[:1800]
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
            partes.append(resultado["stdout"][:2500])
        if resultado.get("stderr"):
            partes.append(f"[STDERR]\n{resultado['stderr'][:1200]}")
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
        "fotos_muestra": [
            {
                "archivo": "test2.jpg",
                "titulo": "Balatas Delanteras Cerámicas",
                "subtitulo": "REP-001 · Pastillas con ranura térmica",
                "url": "/api/fotos-muestra/test2.jpg",
            },
            {
                "archivo": "test.jpg",
                "titulo": "Módulo de Batería Híbrida HV",
                "subtitulo": "REP-035 · Celdas prismáticas y arnés naranja",
                "url": "/api/fotos-muestra/test.jpg",
            },
            {
                "archivo": "test3.jpg",
                "titulo": "Conjunto Transmisión Helicoidal",
                "subtitulo": "REP-036 · Engranajes y diferencial expuesto",
                "url": "/api/fotos-muestra/test3.jpg",
            },
        ],
    })


async def endpoint_foto_muestra(request: Request):
    """Sirve las imágenes reales de data/fotos_prueba/ para previsualización en la UI."""
    nombre = request.path_params.get("nombre", "")
    ruta = (FOTOS_PRUEBA_DIR / nombre).resolve()
    if not ruta.exists() or ruta.parent != FOTOS_PRUEBA_DIR.resolve():
        return JSONResponse({"error": "Fotografía no encontrada."}, status_code=404)
    return FileResponse(str(ruta), media_type="image/jpeg")


async def endpoint_chat(request: Request):
    """Agente conversacional estilo Gemini + chat.py con Bucle ReAct y Streaming SSE."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Cuerpo JSON inválido."}, status_code=400)

    mensajes_usuario = body.get("mensajes", [])
    usar_tools = bool(body.get("usar_tools", True))

    mensajes = [{"role": "system", "content": SYSTEM_CHAT_AGENTE}]
    for m in mensajes_usuario:
        rol = m.get("role", "user")
        contenido = str(m.get("content", "")).strip()
        acciones_previas = m.get("acciones_resumen", "")
        if rol == "assistant" and acciones_previas:
            contenido = f"[Herramientas ejecutadas en este turno: {acciones_previas}]\n{contenido}".strip()
        if rol in ("user", "assistant") and contenido:
            mensajes.append({"role": rol, "content": contenido})

    inicio = time.time()

    async def generador_sse():
        cliente = None
        pt_total = 0
        ct_total = 0
        try:
            cliente = config.crear_cliente()

            for iteracion in range(1, MAX_ITERACIONES_CHAT + 1):
                kwargs_llm = {
                    "model": config.MODEL,
                    "messages": mensajes,
                    "temperature": 0.3,
                    "stream": True,
                }
                if usar_tools:
                    kwargs_llm["tools"] = TOOLS_CHAT_AGENTE
                    kwargs_llm["tool_choice"] = "auto"

                stream = await cliente.chat.completions.create(**kwargs_llm)

                texto_iteracion = []
                tool_calls_acum: dict[int, dict] = {}
                pt_iter = None
                ct_iter = None

                async for chunk in stream:
                    if getattr(chunk, "usage", None):
                        pt_iter = getattr(chunk.usage, "prompt_tokens", None)
                        ct_iter = getattr(chunk.usage, "completion_tokens", None)

                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if not delta:
                        continue

                    if delta.content:
                        texto_iteracion.append(delta.content)
                        payload_tok = json.dumps(
                            {"tipo": "token", "contenido": delta.content},
                            ensure_ascii=False,
                        )
                        yield f"data: {payload_tok}\n\n"

                    if getattr(delta, "tool_calls", None):
                        for tc in delta.tool_calls:
                            idx = getattr(tc, "index", 0) or 0
                            if idx not in tool_calls_acum:
                                tool_calls_acum[idx] = {
                                    "id": getattr(tc, "id", None) or f"call_{iteracion}_{idx}",
                                    "name": "",
                                    "arguments": "",
                                }
                            if getattr(tc, "id", None):
                                tool_calls_acum[idx]["id"] = tc.id
                            if getattr(tc, "function", None):
                                if tc.function.name:
                                    tool_calls_acum[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acum[idx]["arguments"] += tc.function.arguments

                texto_unido = "".join(texto_iteracion)
                if pt_iter is not None and ct_iter is not None:
                    pt_total += pt_iter
                    ct_total += ct_iter
                else:
                    pt_total += max(20, sum(len(str(m.get("content", ""))) // 4 for m in mensajes) + 60)
                    ct_total += max(8, (len(texto_unido) + sum(len(v["arguments"]) for v in tool_calls_acum.values())) // 4)

                # Si no invocó herramientas, el agente terminó su respuesta
                if not tool_calls_acum:
                    break

                # Si emitió texto intermedio antes de una tool, agregamos salto limpio
                if texto_unido and not texto_unido.endswith("\n\n"):
                    yield f"data: {json.dumps({'tipo': 'token', 'contenido': '\n\n'}, ensure_ascii=False)}\n\n"

                lista_tool_calls = [tool_calls_acum[k] for k in sorted(tool_calls_acum.keys())]
                mensajes.append({
                    "role": "assistant",
                    "content": texto_unido or None,
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

                # Ejecutar cada herramienta real en hilo separado sin bloquear SSE
                for tc in lista_tool_calls:
                    nombre = tc["name"]
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                        if not isinstance(args, dict):
                            args = {}
                    except Exception:
                        args = {}

                    ev_ini = {
                        "tipo": "tool_inicio",
                        "id": tc["id"],
                        "iteracion": iteracion,
                        "herramienta": nombre,
                        "argumentos": args,
                    }
                    yield f"data: {json.dumps(ev_ini, ensure_ascii=False)}\n\n"

                    t_tool = time.time()
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

                    ev_fin = {
                        "tipo": "tool_fin",
                        "id": tc["id"],
                        "iteracion": iteracion,
                        "herramienta": nombre,
                        "argumentos": args,
                        "resumen": resumen_ui,
                        "detalle": detalle_ui,
                        "exito": exito_tool,
                        "duracion_ms": duracion_ms,
                    }
                    yield f"data: {json.dumps(ev_fin, ensure_ascii=False)}\n\n"

                    mensajes.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": nombre,
                        "content": json.dumps(resultado_tool, ensure_ascii=False),
                    })

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
            yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        except Exception as e:
            err_payload = json.dumps({"tipo": "error", "error": str(e)}, ensure_ascii=False)
            yield f"data: {err_payload}\n\n"
        finally:
            if cliente is not None:
                try:
                    await cliente.close()
                except Exception:
                    pass

    return StreamingResponse(
        generador_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class _CompletionsConFallo429:
    """Wrapper para demostrar en vivo en la UI la recuperación ante HTTP 429."""

    def __init__(self, real_completions):
        self._real = real_completions
        self.intentos = 0

    async def create(self, *args, **kwargs):
        self.intentos += 1
        if self.intentos == 1:
            req = httpx.Request("POST", "https://api.reto.pltk.mx/v1/chat/completions")
            resp = httpx.Response(status_code=429, request=req)
            raise openai.RateLimitError(
                message="429 Too Many Requests: límite de tasa simulado desde Platica AI Studio.",
                response=resp,
                body={"error": {"message": "Rate limit exceeded"}},
            )
        return await self._real.create(*args, **kwargs)


class _ClienteConSimulacion429:
    def __init__(self, cliente_real):
        self.chat = type(
            "ChatProxy",
            (),
            {"completions": _CompletionsConFallo429(cliente_real.chat.completions)},
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

            if muestra_1 and isinstance(muestra_1, str) and muestra_1.strip():
                ruta_1 = FOTOS_PRUEBA_DIR / muestra_1.strip()
            elif foto_1 and hasattr(foto_1, "read"):
                contenido_1 = await foto_1.read()
                sufijo = Path(getattr(foto_1, "filename", "foto1.jpg")).suffix or ".jpg"
                tmp1 = tempfile.NamedTemporaryFile(delete=False, suffix=sufijo)
                tmp1.write(contenido_1)
                tmp1.close()
                ruta_1 = Path(tmp1.name)
                archivos_temp.append(ruta_1)

            if muestra_2 and isinstance(muestra_2, str) and muestra_2.strip():
                ruta_2 = FOTOS_PRUEBA_DIR / muestra_2.strip()
            elif foto_2 and hasattr(foto_2, "read"):
                contenido_2 = await foto_2.read()
                sufijo2 = Path(getattr(foto_2, "filename", "foto2.jpg")).suffix or ".jpg"
                tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=sufijo2)
                tmp2.write(contenido_2)
                tmp2.close()
                ruta_2 = Path(tmp2.name)
                archivos_temp.append(ruta_2)
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
        cliente = _ClienteConSimulacion429(cliente_real) if simular_429 else cliente_real

        resultado = await ejecutar_agente(
            str(ruta_1),
            str(ruta_2) if (ruta_2 and ruta_2.exists()) else None,
            cliente=cliente,
        )
        return JSONResponse(resultado)
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
    uvicorn.run(app, host="127.0.0.1", port=8000)
