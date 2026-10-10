import asyncio
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Cargar variables de entorno desde .env
load_dotenv()

# Inicializamos el cliente apuntando a la API de Platica
client = AsyncOpenAI(
    base_url=os.getenv("base_url") or os.getenv("PLATICA_BASE_URL"),
    api_key=os.getenv("api_key") or os.getenv("PLATICA_API_KEY"),
)

# Modelo predeterminado
MODEL_NAME = os.getenv("PLATICA_MODEL", "grok-4.7")

async def main():
    print("Iniciando el Agente de IA para Platica (vía Grok / OpenAI API)...")
    
    # Prompt del sistema (System Instructions)
    system_prompt = (
        "Eres un agente de IA experto en repuestos de autopartes para Platica. "
        "Tu objetivo es ayudar a identificar piezas, consultar catálogos "
        "y generar cotizaciones claras para los clientes."
    )
    
    # Historial de conversación
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    print("¡Agente inicializado con éxito!\n")
    print("Escribe 'salir' para terminar la conversación.")
    
    while True:
        user_input = input("\nCliente: ")
        if user_input.lower() == 'salir':
            print("Cerrando sesión del agente. ¡Hasta luego!")
            break
            
        messages.append({"role": "user", "content": user_input})
        
        print("\nAgente: ", end="", flush=True)
        assistant_response = ""
        
        try:
            # Petición con streaming
            stream = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                stream=True,
            )
            
            async for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                print(token, end="", flush=True)
                assistant_response += token
                
            print()
            messages.append({"role": "assistant", "content": assistant_response})
            
        except Exception as e:
            print(f"\n[Error de conexión con la API de Platica]: {e}")

if __name__ == "__main__":
    asyncio.run(main())
