import asyncio
import os
from dotenv import load_dotenv
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

# Cargar variables de entorno desde el archivo .env
load_dotenv()

async def main():
    print("Iniciando el Agente de IA para Platica...")
    
    # Configuramos el agente con nuestra instrucción del sistema (System Prompt) base
    config = LocalAgentConfig(
        system_instructions=(
            "Eres un agente de IA experto en repuestos de autopartes. "
            "Tu objetivo es ayudar a identificar piezas, consultar catálogos "
            "y generar cotizaciones claras para los clientes."
        ),
        # Por ahora habilitamos las capacidades por defecto
        capabilities=CapabilitiesConfig(),
    )
    
    # Instanciamos el agente usando un manejador de contexto asíncrono
    async with Agent(config) as agent:
        print("¡Agente inicializado con éxito!\n")
        print("Escribe 'salir' para terminar la conversación.")
        
        # Bucle interactivo para conversar por terminal
        while True:
            user_input = input("\nCliente: ")
            if user_input.lower() == 'salir':
                break
                
            print("\nAgente:")
            # Enviamos el mensaje al agente (todavía sin fotos ni herramientas, solo texto)
            response = await agent.chat(user_input)
            
            # Mostramos la respuesta en tiempo real (streaming)
            async for token in response:
                print(token, end="", flush=True)
            print()

if __name__ == "__main__":
    asyncio.run(main())