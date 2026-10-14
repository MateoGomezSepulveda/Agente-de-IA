"""Agente de IA Autónomo por Consola (CLI).

Funciona como un agente de ingeniería de software con herramientas reales:
- listar_directorio: explorar archivos del proyecto
- leer_archivo: inspeccionar código y documentos
- escribir_archivo: crear y modificar archivos
- ejecutar_comando: ejecutar comandos en la terminal (PowerShell)
"""
import sys
import os
import json
import asyncio
import subprocess
from pathlib import Path
import openai

# Asegurar acceso a la raíz del proyecto
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.config import crear_cliente, MODEL

# --- 1. DEFINICIÓN DE HERRAMIENTAS (TOOLS) DEL AGENTE ---
TOOLS_AGENTE = [
    {
        "type": "function",
        "function": {
            "name": "listar_directorio",
            "description": "Lista los archivos y subcarpetas dentro de una ruta para explorar el proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta relativa o absoluta a explorar. Por defecto '.' (raíz del proyecto)."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "leer_archivo",
            "description": "Lee el contenido de un archivo de texto en el sistema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta relativa o absoluta del archivo que deseas inspeccionar."
                    }
                },
                "required": ["ruta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escribir_archivo",
            "description": "Crea o sobreescribe un archivo con código o contenido específico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta del archivo a crear o modificar."
                    },
                    "contenido": {
                        "type": "string",
                        "description": "Texto o código completo a escribir en el archivo."
                    }
                },
                "required": ["ruta", "contenido"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ejecutar_comando",
            "description": "Ejecuta un comando en la terminal (PowerShell) y devuelve stdout, stderr y código de salida.",
            "parameters": {
                "type": "object",
                "properties": {
                    "comando": {
                        "type": "string",
                        "description": "Comando de shell a ejecutar (ej. 'python scripts/verificar_vision.py', 'dir', etc.)."
                    }
                },
                "required": ["comando"]
            }
        }
    }
]


# --- 2. IMPLEMENTACIÓN REAL DE LAS HERRAMIENTAS ---
def ejecutar_listar_directorio(ruta: str = ".") -> dict:
    try:
        p = Path(ruta)
        if not p.is_absolute():
            p = RAIZ / p
        if not p.exists():
            return {"error": f"La ruta '{ruta}' no existe."}
        items = []
        for item in sorted(p.iterdir()):
            items.append({
                "nombre": item.name,
                "es_directorio": item.is_dir(),
                "tamano_bytes": item.stat().st_size if item.is_file() else None
            })
        return {"ruta": str(p), "total": len(items), "items": items}
    except Exception as e:
        return {"error": str(e)}


def ejecutar_leer_archivo(ruta: str) -> dict:
    try:
        p = Path(ruta)
        if not p.is_absolute():
            p = RAIZ / p
        if not p.exists():
            return {"error": f"El archivo '{ruta}' no existe."}
        if p.is_dir():
            return {"error": f"'{ruta}' es un directorio, usa listar_directorio."}
        contenido = p.read_text(encoding="utf-8", errors="replace")
        if len(contenido) > 25000:
            return {
                "contenido": contenido[:25000],
                "aviso": "El archivo es muy grande, se muestran los primeros 25,000 caracteres."
            }
        return {"ruta": str(p), "contenido": contenido}
    except Exception as e:
        return {"error": str(e)}


def ejecutar_escribir_archivo(ruta: str, contenido: str) -> dict:
    try:
        p = Path(ruta)
        if not p.is_absolute():
            p = RAIZ / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")
        return {"exito": True, "ruta": str(p), "bytes_escritos": len(contenido.encode("utf-8"))}
    except Exception as e:
        return {"error": str(e)}


def ejecutar_comando_terminal(comando: str) -> dict:
    try:
        resultado = subprocess.run(
            comando,
            shell=True,
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(RAIZ),
            encoding="utf-8",
            errors="replace"
        )
        return {
            "codigo_salida": resultado.returncode,
            "stdout": resultado.stdout.strip(),
            "stderr": resultado.stderr.strip()
        }
    except subprocess.TimeoutExpired:
        return {"error": "El comando superó el tiempo límite de ejecución (45s)."}
    except Exception as e:
        return {"error": str(e)}


FUNCIONES_MAP = {
    "listar_directorio": ejecutar_listar_directorio,
    "leer_archivo": ejecutar_leer_archivo,
    "escribir_archivo": ejecutar_escribir_archivo,
    "ejecutar_comando": ejecutar_comando_terminal
}


# --- 3. BUCLE DEL AGENTE (REASONING & ACTING) ---
async def iniciar_agente() -> None:
    try:
        cliente = crear_cliente()
    except RuntimeError as e:
        print(f"\n❌ Error de configuración: {e}")
        return

    print("=" * 65)
    print(f"🤖 AGENTE AUTÓNOMO DE IA (Modo Asistente de Código)")
    print(f"⚡ Modelo: {MODEL} | Endpoint: Platica AI")
    print("=" * 65)
    print("Capacidades activas del Agente:")
    print("  • 📂 Explorar archivos (listar_directorio)")
    print("  • 📄 Leer archivos de código (leer_archivo)")
    print("  • ✏️ Crear y editar código (escribir_archivo)")
    print("  • 💻 Ejecutar comandos en terminal (ejecutar_comando)")
    print("-" * 65)
    print("Comandos: 'salir' para cerrar | 'limpiar' para reiniciar memoria")
    print("=" * 65 + "\n")

    system_prompt = (
        "Eres un Agente Autónomo de Inteligencia Artificial para Desarrollo de Software, "
        "similar a Antigravity o Cursor, ejecutándote en la terminal local del usuario en Windows.\n"
        "Cuentas con herramientas reales para interactuar con el entorno de trabajo:\n"
        "- 'listar_directorio': para ver archivos y carpetas del proyecto.\n"
        "- 'leer_archivo': para inspeccionar código antes de proponer cambios o responder preguntas.\n"
        "- 'escribir_archivo': para crear nuevos scripts, módulos o actualizar archivos.\n"
        "- 'ejecutar_comando': para correr comandos en la consola (PowerShell), ejecutar tests o verificar scripts.\n\n"
        "REGLAS DE CONDUCTA:\n"
        "1. Sé proactivo y resolutivo: cuando el usuario te pida una tarea (por ejemplo: 'crea un script X y pruébalo'), "
        "no te limites a dar explicaciones teóricas; USA tus herramientas, crea el archivo y ejecútalo para verificar el resultado.\n"
        "2. Piensa antes de actuar. Si te preguntan sobre un archivo del proyecto, primero léelo con 'leer_archivo'.\n"
        "3. Sé pedagógico y cercano: explica qué hiciste, qué herramientas llamaste y qué resultado obtuviste.\n"
        "4. Siempre responde en español."
    )

    historial = [{"role": "system", "content": system_prompt}]
    total_prompt_sesion = 0
    total_completion_sesion = 0
    MAX_ITERACIONES = 8

    while True:
        try:
            mensaje_usuario = input("\n👤 Tú: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nSaliendo del agente...")
            break

        if not mensaje_usuario:
            continue

        comando_rapido = mensaje_usuario.lower()
        if comando_rapido in ["salir", "exit"]:
            print("\n👋 ¡Agente finalizado!")
            break

        if comando_rapido in ["limpiar", "clear"]:
            historial = [historial[0]]
            print("\n🧹 Memoria del agente reiniciada.")
            continue

        historial.append({"role": "user", "content": mensaje_usuario})

        # Bucle ReAct (Reasoning + Acting)
        for iteracion in range(MAX_ITERACIONES):
            print("\n🧠 Pensando...", end="", flush=True)

            try:
                respuesta = await cliente.chat.completions.create(
                    model=MODEL,
                    messages=historial,
                    tools=TOOLS_AGENTE,
                    tool_choice="auto",
                    temperature=0.3
                )
            except Exception as e:
                print(f"\r❌ Error al comunicar con la API: {e}")
                break

            print("\r" + " " * 20 + "\r", end="")

            if respuesta.usage:
                total_prompt_sesion += respuesta.usage.prompt_tokens
                total_completion_sesion += respuesta.usage.completion_tokens

            mensaje_asistente = respuesta.choices[0].message
            historial.append(mensaje_asistente)

            # Si el modelo incluye razonamiento o texto
            if mensaje_asistente.content:
                print(f"🤖 Agente: {mensaje_asistente.content}\n")

            # Si el modelo NO pidió usar herramientas, terminó su turno
            if not mensaje_asistente.tool_calls:
                break

            # Si el modelo pidió herramientas, las ejecutamos en su máquina
            for tool_call in mensaje_asistente.tool_calls:
                nombre = tool_call.function.name
                args_str = tool_call.function.arguments
                try:
                    args = json.loads(args_str)
                except Exception:
                    args = {}

                print(f"   ⚙️  [Acción]: {nombre}({json.dumps(args, ensure_ascii=False)})")

                # Ejecución de la herramienta
                if nombre in FUNCIONES_MAP:
                    resultado_tool = FUNCIONES_MAP[nombre](**args)
                else:
                    resultado_tool = {"error": f"Herramienta '{nombre}' desconocida."}

                # Mostrar un resumen breve en consola
                if nombre == "ejecutar_comando":
                    stdout = resultado_tool.get("stdout")
                    stderr = resultado_tool.get("stderr")
                    if stdout:
                        print(f"       └─ 📤 [Salida]:\n{stdout[:300]}")
                    if stderr:
                        print(f"       └─ ⚠️ [Error]:\n{stderr[:300]}")
                elif nombre == "leer_archivo":
                    print(f"       └─ 📖 Archivo leído ({len(resultado_tool.get('contenido', ''))} caracteres)")
                elif nombre == "escribir_archivo":
                    print(f"       └─ ✍️ Archivo guardado correctamente en: {resultado_tool.get('ruta')}")
                elif nombre == "listar_directorio":
                    print(f"       └─ 📂 Se encontraron {resultado_tool.get('total', 0)} elementos")

                # Devolver el resultado de la herramienta al LLM
                historial.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": nombre,
                    "content": json.dumps(resultado_tool, ensure_ascii=False)
                })

        # Mostrar métricas de tokens de la sesión
        total_tokens = total_prompt_sesion + total_completion_sesion
        print(f"⚡ [Tokens acumulados sesión: {total_tokens:,}]")


if __name__ == "__main__":
    asyncio.run(iniciar_agente())
