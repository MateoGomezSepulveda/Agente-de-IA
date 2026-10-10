import asyncio
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

async def probar_tool_calling():
    client = AsyncOpenAI(
        base_url=os.getenv("PLATICA_BASE_URL"),
        api_key=os.getenv("PLATICA_API_KEY")
    )
    model = os.getenv("PLATICA_MODEL", "grok-4.7")

    # Definimos el esquema de una herramienta falsa (solo la estructura)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "consultar_inventario",
                "description": "Consulta el inventario y precio de una pieza automotriz específica.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pieza": {
                            "type": "string",
                            "description": "Nombre de la pieza (ej. balatas, filtro de aceite)"
                        },
                        "marca_vehiculo": {
                            "type": "string",
                            "description": "Marca del vehículo (ej. Honda, Toyota)"
                        }
                    },
                    "required": ["pieza", "marca_vehiculo"]
                }
            }
        }
    ]

    print(f"Probando Tool Calling con el modelo {model}...")
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "¿Tienen balatas para un Honda Civic?"}
            ],
            tools=tools,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        
        if message.tool_calls:
            print("\n✅ ¡Éxito! El modelo solicitó usar una herramienta.")
            for tool_call in message.tool_calls:
                print(f"Herramienta solicitada: {tool_call.function.name}")
                print(f"Argumentos extraídos: {tool_call.function.arguments}")
        else:
            print("\n⚠️ El modelo no usó la herramienta y respondió directamente con texto:")
            print(message.content)
            
    except Exception as e:
        print(f"\n❌ Error al procesar tool calling: {e}")

if __name__ == "__main__":
    asyncio.run(probar_tool_calling())