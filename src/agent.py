import json
from src.config import MAX_ITERACIONES, MODEL, crear_cliente
from src.vision import procesar_imagen_base64
from src.tools import buscar_en_catalogo, consultar_inventario

# 1. ESQUEMAS: Aquí le explicamos al LLM qué herramientas existen y cómo usarlas
ESQUEMAS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_en_catalogo",
            "description": "Busca repuestos en el catálogo usando palabras clave (ej. balatas, filtro). Retorna los candidatos y vehículos compatibles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "palabras_clave": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Palabras extraídas de la imagen para buscar."
                    }
                },
                "required": ["palabras_clave"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_inventario",
            "description": "Consulta el ERP para obtener precio, stock y ubicación usando un id_repuesto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_repuesto": {
                        "type": "string",
                        "description": "ID oficial del repuesto (ej. REP-001)"
                    }
                },
                "required": ["id_repuesto"]
            }
        }
    }
]

# Mapa para conectar el texto del LLM con nuestras funciones reales de Python
FUNCIONES = {
    "buscar_en_catalogo": buscar_en_catalogo,
    "consultar_inventario": consultar_inventario
}

async def ejecutar_agente(ruta_imagen: str):
    """
    Ciclo principal del Agente. Analiza la foto, usa herramientas automáticamente
    y emite el resultado final.
    """
    cliente = crear_cliente()
    base64_image = procesar_imagen_base64(ruta_imagen)
    
    # El "System Prompt" dicta la personalidad y reglas estrictas del agente
    system_prompt = (
        "Eres un experto automotriz de Platica. Tu trabajo es ver la foto, "
        "identificar la pieza visualmente, usar 'buscar_en_catalogo' para ver la compatibilidad, "
        "y usar 'consultar_inventario' para ver el precio. "
        "REGLA DE ORO: NUNCA inventes precios, IDs ni vehículos compatibles. Usa SIEMPRE "
        "los datos que te devuelvan las herramientas."
    )
    
    # Historial inicial
    mensajes = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user", 
            "content": [
                {"type": "text", "text": "Identifica esta pieza, dime sus compatibles y cotízala."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }
    ]
    
    print(f"🧠 Iniciando agente con modelo {MODEL}...")
    
    # EL BUCLE DEL AGENTE
    for iteracion in range(MAX_ITERACIONES):
        print(f"🔄 Pensando (Iteración {iteracion + 1})...")
        
        respuesta = await cliente.chat.completions.create(
            model=MODEL,
            messages=mensajes,
            tools=ESQUEMAS_TOOLS,
            tool_choice="auto"
        )
        
        mensaje_llm = respuesta.choices[0].message
        mensajes.append(mensaje_llm) # Guardamos su respuesta en el historial
        
        # Si NO pidió herramientas, ¡Terminó su trabajo y nos da la respuesta final!
        if not mensaje_llm.tool_calls:
            print("\n✅ ¡Respuesta Final Alcanzada!\n")
            return mensaje_llm.content
            
        # Si SÍ pidió herramientas, las ejecutamos
        for tool_call in mensaje_llm.tool_calls:
            nombre_funcion = tool_call.function.name
            argumentos = json.loads(tool_call.function.arguments)
            print(f"   ⚙️  Ejecutando: {nombre_funcion} con argumentos {argumentos}")
            
            if nombre_funcion in FUNCIONES:
                resultado_python = FUNCIONES[nombre_funcion](**argumentos)
            else:
                resultado_python = {"error": "Herramienta desconocida"}
                
            # Le pasamos el resultado crudo al modelo
            mensajes.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": nombre_funcion,
                "content": json.dumps(resultado_python)
            })

    return "⚠️ Error: Se superó el límite de iteraciones sin llegar a una conclusión."

# --- PRUEBA LOCAL ---
if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    
    ruta_prueba = Path(__file__).resolve().parent.parent / "data" / "fotos_prueba" / "test.jpg"
    resultado = asyncio.run(ejecutar_agente(str(ruta_prueba)))
    print("="*40)
    print(resultado)