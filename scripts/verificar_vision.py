import asyncio
import os
import base64
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# Función para codificar la imagen local a base64
def codificar_imagen(ruta_imagen):
    with open(ruta_imagen, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

async def probar_vision():
    client = AsyncOpenAI(
        base_url=os.getenv("PLATICA_BASE_URL"),
        api_key=os.getenv("PLATICA_API_KEY")
    )
    model = os.getenv("PLATICA_MODEL", "grok-4.7")
    
    ruta_local = "data/fotos_prueba/test.jpg"
    
    if not os.path.exists(ruta_local):
        print(f"Por favor coloca una imagen en: {ruta_local}")
        return
        
    print("Codificando imagen a base64...")
    base64_image = codificar_imagen(ruta_local)
    
    print(f"Enviando imagen local al modelo {model} en el endpoint de Platica...")
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "¿Qué objeto o pieza automotriz ves en esta imagen? Responde brevemente."},
                        {
                            "type": "image_url",
                            "image_url": {
                                # Pasamos la imagen directamente codificada
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ],
                }
            ],
            max_tokens=150
        )
        print("\nExito! Respuesta del modelo:")
        print(response.choices[0].message.content)
    except Exception as e:
        print(f"\nError al procesar vision: {e}")

if __name__ == "__main__":
    asyncio.run(probar_vision())