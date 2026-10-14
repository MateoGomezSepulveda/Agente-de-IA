"""Bucle de tool calling del agente.

El modelo interpreta la foto y pide herramientas. El código ejecuta esas
herramientas, valida la respuesta y es la única fuente de precios,
stock y vehículos compatibles.
"""
import asyncio
import json
import time
import uuid

import openai

from src import config
from src.tools import FUNCIONES, ESQUEMAS_TOOLS, cargar_catalogo
from src.tracking import registrar_uso
from src.vision import procesar_imagen_base64

ESTADOS = {"cotizado", "necesita_otra_foto", "derivar_a_humano"}
CAMPOS_OBLIGATORIOS = ("estado", "pieza", "vehiculos_compatibles", "cotizacion", "motivo")

SYSTEM_PROMPT = (
    "Eres el agente de refacciones de Platica. La única entrada es la foto de una pieza rota.\n"
    "Flujo obligatorio:\n"
    "1. Describe lo que ves y llama buscar_en_catalogo con atributos visuales concretos.\n"
    "2. Con el id del mejor candidato, llama consultar_inventario.\n"
    "3. Solo si la pieza es clara y hay stock, llama generar_cotizacion.\n"
    "Reglas:\n"
    "- Nunca inventes precios, stock, códigos, IDs ni vehículos. Copia solo lo que devuelvan las herramientas.\n"
    "- Si la foto no alcanza para distinguir la pieza, responde necesita_otra_foto e indica qué mostrar.\n"
    "- Si ya hay dos fotos y sigues sin poder cotizar, responde derivar_a_humano.\n"
    "- Tu mensaje final es un único objeto JSON, sin markdown, con estas llaves:\n"
    '{"estado":"cotizado | necesita_otra_foto | derivar_a_humano",'
    '"pieza":{"id":"","nombre":"","codigo_oem":"","confianza":0.0},'
    '"vehiculos_compatibles":[{"marca":"","modelo":"","anio_desde":0,"anio_hasta":0}],'
    '"cotizacion":{"precio_unitario":0.0,"stock":0,"ubicacion":"","total":0.0},'
    '"alternativas":[],'
    '"foto_adicional_solicitada":"",'
    '"motivo":""}'
)


def _indice_catalogo():
    return {item["id_repuesto"]: item for item in cargar_catalogo()}


def _extraer_json(texto):
    if not texto or not texto.strip():
        raise ValueError("El modelo no devolvió contenido.")
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.split("\n", 1)[-1]
        limpio = limpio.removesuffix("```").strip()
    inicio = limpio.find("{")
    fin = limpio.rfind("}")
    if inicio == -1 or fin == -1 or fin < inicio:
        raise ValueError("La respuesta no contiene un objeto JSON.")
    return json.loads(limpio[inicio : fin + 1])


def validar_respuesta(datos, fotos_recibidas, resultados_tools):
    """Rechaza alucinaciones: estado, campos y datos que no salieron de una tool."""
    if not isinstance(datos, dict):
        raise ValueError("La respuesta final no es un objeto JSON.")
    faltan = [campo for campo in CAMPOS_OBLIGATORIOS if campo not in datos]
    if faltan:
        raise ValueError(f"Faltan campos en la respuesta: {', '.join(faltan)}.")
    if datos["estado"] not in ESTADOS:
        raise ValueError(f"Estado no permitido: {datos['estado']}.")
    if datos["estado"] == "necesita_otra_foto" and fotos_recibidas > config.MAX_FOTOS_EXTRA + 1:
        raise ValueError("No se puede pedir otra foto: ya se usó el máximo.")
    if datos["estado"] == "necesita_otra_foto" and not str(datos.get("foto_adicional_solicitada", "")).strip():
        raise ValueError("necesita_otra_foto exige foto_adicional_solicitada.")

    pieza = datos.get("pieza") or {}
    pieza_id = pieza.get("id")
    if datos["estado"] == "cotizado":
        if not pieza_id:
            raise ValueError("Una cotización exige el id de la pieza.")
        inventario = resultados_tools["inventario"].get(pieza_id)
        cotizacion_real = resultados_tools["cotizaciones"].get(pieza_id)
        if not inventario:
            raise ValueError(f"Se cotizó {pieza_id} sin haberlo consultado en inventario.")
        if not cotizacion_real:
            raise ValueError(f"Se cotizó {pieza_id} sin generar_cotizacion.")
        cotizacion = datos.get("cotizacion") or {}
        for campo in ("precio_unitario", "total", "stock"):
            if cotizacion.get(campo) != cotizacion_real.get(campo):
                raise ValueError(
                    f"El modelo alteró {campo}: dijo {cotizacion.get(campo)} "
                    f"y la herramienta devolvió {cotizacion_real.get(campo)}."
                )

    if pieza_id and pieza_id in resultados_tools["catalogo"]:
        oficiales = resultados_tools["catalogo"][pieza_id].get("vehiculos_compatibles", [])
        if datos.get("vehiculos_compatibles") != oficiales:
            raise ValueError("Los vehículos compatibles no coinciden con el catálogo.")
    return datos


def _registrar_resultado(nombre, argumentos, resultado, resultados_tools):
    if nombre == "buscar_en_catalogo" and isinstance(resultado, dict):
        for candidato in resultado.get("candidatos", []):
            resultados_tools["catalogo"][candidato["id_repuesto"]] = candidato
    elif nombre == "consultar_inventario" and isinstance(resultado, dict) and "id_repuesto" in resultado:
        resultados_tools["inventario"][resultado["id_repuesto"]] = resultado
    elif nombre == "generar_cotizacion" and isinstance(resultado, dict) and "total" in resultado:
        resultados_tools["cotizaciones"][resultado["id_repuesto"]] = resultado


async def _llamar_modelo(cliente, mensajes):
    """Reintentos acotados. 402 y autenticación no se reintentan: no hay crédito que gastar."""
    espera = 2
    ultimo_error = None
    for intento in range(3):
        try:
            return await cliente.chat.completions.create(
                model=config.MODEL,
                messages=mensajes,
                tools=ESQUEMAS_TOOLS,
                tool_choice="auto",
                timeout=30.0,
            )
        except openai.RateLimitError as e:
            ultimo_error = e
            print(f"Límite de tasa (429). Reintento {intento + 1} en {espera}s.")
            await asyncio.sleep(espera)
            espera *= 2
        except openai.APIStatusError as e:
            if getattr(e, "status_code", None) == 402:
                raise RuntimeError("Sin créditos en el endpoint (402). No se reintenta.") from e
            raise
        except openai.AuthenticationError as e:
            raise RuntimeError("API key rechazada. Revisa PLATICA_API_KEY.") from e
        except openai.APITimeoutError as e:
            ultimo_error = e
            print(f"Timeout. Reintento {intento + 1} en {espera}s.")
            await asyncio.sleep(espera)
            espera *= 2
        except openai.APIConnectionError as e:
            raise RuntimeError("Sin conexión con el endpoint.") from e
    raise RuntimeError(f"Se agotaron los reintentos: {ultimo_error}")


def _ejecutar_tool(tool_call, resultados_tools, tarea_id):
    nombre = tool_call.function.name
    try:
        argumentos = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        argumentos = {}
        resultado = {"error": "El modelo envió argumentos que no son JSON."}
        return nombre, argumentos, resultado

    if not isinstance(argumentos, dict):
        return nombre, {}, {"error": "Los argumentos de la herramienta deben ser un objeto."}

    funcion = FUNCIONES.get(nombre)
    if funcion is None:
        resultado = {"error": f"Herramienta desconocida: {nombre}."}
    else:
        if nombre == "generar_cotizacion":
            argumentos = {**argumentos, "tarea_id": tarea_id}
        try:
            resultado = funcion(**argumentos)
        except TypeError as e:
            resultado = {"error": f"Argumentos inválidos para {nombre}: {e}"}
        except Exception as e:
            resultado = {"error": f"{nombre} falló: {e}"}
    _registrar_resultado(nombre, argumentos, resultado, resultados_tools)
    return nombre, argumentos, resultado


async def ejecutar_agente(ruta_imagen, ruta_segunda_imagen=None, cliente=None):
    """Foto entra, respuesta estructurada sale. `cliente` permite inyectar el mock."""
    fotos = [ruta_imagen] + ([ruta_segunda_imagen] if ruta_segunda_imagen else [])
    if len(fotos) > config.MAX_FOTOS_EXTRA + 1:
        return {"error": "Solo se acepta una foto adicional."}

    imagenes = [procesar_imagen_base64(ruta) for ruta in fotos]
    if cliente is None:
        cliente = config.crear_cliente()

    tarea_id = f"tarea_{uuid.uuid4().hex[:8]}"
    inicio = time.time()
    tokens_entrada = 0
    tokens_salida = 0
    resultados_tools = {"catalogo": {}, "inventario": {}, "cotizaciones": {}}
    traza = []

    contenido = [{"type": "text", "text": "Identifica la pieza de la foto, busca compatibles y cotiza solo con las herramientas."}]
    for i, imagen in enumerate(imagenes, start=1):
        if i > 1:
            contenido.append({"type": "text", "text": "Segunda y última foto del mismo caso."})
        contenido.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{imagen}"}})
    mensajes = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": contenido},
    ]

    for iteracion in range(1, config.MAX_ITERACIONES + 1):
        respuesta = await _llamar_modelo(cliente, mensajes)
        if respuesta.usage:
            tokens_entrada += respuesta.usage.prompt_tokens or 0
            tokens_salida += respuesta.usage.completion_tokens or 0

        mensaje = respuesta.choices[0].message
        mensajes.append(mensaje)
        if not mensaje.tool_calls:
            try:
                datos = validar_respuesta(
                    _extraer_json(mensaje.content), len(fotos), resultados_tools
                )
            except (ValueError, json.JSONDecodeError) as e:
                datos = {
                    "estado": "derivar_a_humano",
                    "pieza": {},
                    "vehiculos_compatibles": [],
                    "cotizacion": None,
                    "motivo": f"La respuesta del modelo no pasó la validación: {e}",
                    "error_validacion": str(e),
                }
            datos["tarea_id"] = tarea_id
            datos["tracking"] = registrar_uso(
                tarea_id, config.MODEL, tokens_entrada, tokens_salida, time.time() - inicio, traza
            )
            return datos

        for tool_call in mensaje.tool_calls:
            nombre, argumentos, resultado = _ejecutar_tool(tool_call, resultados_tools, tarea_id)
            traza.append(
                {
                    "iteracion": iteracion,
                    "herramienta": nombre,
                    "argumentos": {k: v for k, v in argumentos.items() if k != "tarea_id"},
                    "resultado": resultado,
                }
            )
            mensajes.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                }
            )

    datos = {
        "estado": "derivar_a_humano",
        "pieza": {},
        "vehiculos_compatibles": [],
        "cotizacion": None,
        "motivo": f"Se alcanzó el máximo de {config.MAX_ITERACIONES} iteraciones sin una respuesta final.",
        "tarea_id": tarea_id,
    }
    datos["tracking"] = registrar_uso(
        tarea_id, config.MODEL, tokens_entrada, tokens_salida, time.time() - inicio, traza
    )
    return datos


if __name__ == "__main__":
    from pathlib import Path

    ruta = Path(__file__).resolve().parent.parent / "data" / "fotos_prueba" / "test.jpg"
    print(json.dumps(asyncio.run(ejecutar_agente(str(ruta))), indent=2, ensure_ascii=False))
