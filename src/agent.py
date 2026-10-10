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

async def ejecutar_agente(ruta_imagen: str, ruta_segunda_imagen: str = None):
    """
    Ciclo principal del Agente. Soporta una segunda imagen opcional si la primera no fue suficiente.
    """
    cliente = crear_cliente()
    base64_img1 = procesar_imagen_base64(ruta_imagen)
    
    system_prompt = (
        "Eres un experto automotriz de Platica. Identifica la pieza visualmente, "
        "usa 'buscar_en_catalogo' y luego 'consultar_inventario'.\n"
        "REGLA 1: NUNCA inventes precios, IDs ni vehículos compatibles.\n"
        "REGLA 2: OBLIGATORIAMENTE debes responder SOLO con un objeto JSON válido con esta estructura:\n"
        "{\n"
        '  "estado": "cotizado | necesita_otra_foto | derivar_a_humano",\n'
        '  "pieza": {"id": "...", "nombre": "...", "confianza": 0.0},\n'
        '  "vehiculos_compatibles": [{"marca": "...", "modelo": "...", "anio_desde": 0, "anio_hasta": 0}],\n'
        '  "cotizacion": {"precio_unitario": 0.0, "stock": 0, "total": 0.0},\n'
        '  "foto_adicional_solicitada": "Qué ángulo o etiqueta falta (solo si el estado es necesita_otra_foto)",\n'
        '  "motivo": "explicación breve"\n'
        "}\n"
        "Si necesitas ver otra foto para estar seguro, devuelve estado 'necesita_otra_foto'. "
        "Si ya recibiste dos fotos y sigues sin encontrarla en el catálogo o inventario, tu estado DEBE ser 'derivar_a_humano'."
    )
    
    contenido_usuario = [
        {"type": "text", "text": "Identifica esta pieza, busca sus compatibles en catálogo y cotízala en inventario."}
    ]
    
    # Agregamos la primera foto
    contenido_usuario.append({
        "type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img1}"}
    })
    
    # Si hay una segunda foto, la agregamos al MISMO mensaje para darle contexto completo
    if ruta_segunda_imagen:
        base64_img2 = procesar_imagen_base64(ruta_segunda_imagen)
        contenido_usuario.append({"type": "text", "text": "Aquí tienes una segunda foto con más detalles (ej. etiqueta, otro ángulo):"})
        contenido_usuario.append({
            "type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img2}"}
        })
        
    mensajes = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": contenido_usuario}
    ]
    
    print(f"🧠 Iniciando agente con modelo {MODEL}...")
    
    for iteracion in range(MAX_ITERACIONES):
        print(f"🔄 Pensando (Iteración {iteracion + 1})...")
        
        respuesta = await cliente.chat.completions.create(
            model=MODEL,
            messages=mensajes,
            tools=ESQUEMAS_TOOLS,
            tool_choice="auto"
        )
        
        mensaje_llm = respuesta.choices[0].message
        mensajes.append(mensaje_llm)
        
        if not mensaje_llm.tool_calls:
            print("\n✅ ¡Respuesta Final Alcanzada!\n")
            contenido = mensaje_llm.content.strip()
            
            if contenido.startswith("```json"):
                contenido = contenido[7:-3].strip()
            elif contenido.startswith("```"):
                contenido = contenido[3:-3].strip()
                
            try:
                return json.loads(contenido)
            except json.JSONDecodeError:
                return {"error": "El modelo no devolvió un JSON válido", "texto_crudo": mensaje_llm.content}
                
        for tool_call in mensaje_llm.tool_calls:
            nombre_funcion = tool_call.function.name
            argumentos = json.loads(tool_call.function.arguments)
            print(f"   ⚙️  Ejecutando: {nombre_funcion} con args {argumentos}")
            
            if nombre_funcion in FUNCIONES:
                resultado_python = FUNCIONES[nombre_funcion](**argumentos)
            else:
                resultado_python = {"error": "Herramienta desconocida"}
                
            mensajes.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": nombre_funcion,
                "content": json.dumps(resultado_python)
            })

    return {"error": "Límite de iteraciones superado."}# --- PRUEBA LOCAL ---
if __name__ == "__main__":
    import asyncio
    from pathlib import Path
    
    ruta_prueba = Path(__file__).resolve().parent.parent / "data" / "fotos_prueba" / "test.jpg"
    resultado = asyncio.run(ejecutar_agente(str(ruta_prueba)))
    print("="*40)
    print(resultado)