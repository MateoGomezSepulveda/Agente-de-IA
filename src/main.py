import asyncio
import os
from src.agent import ejecutar_agente

async def main():
    print("==================================================")
    print("🚙 AGENTE DE IA PLATICA - IDENTIFICADOR DE PIEZAS")
    print("==================================================")
    print("Escribe la ruta (absoluta o relativa) de la fotografía de la pieza.")
    print("Escribe 'salir' para terminar el programa.\n")
    
    while True:
        ruta = input("📸 Ruta de la imagen: ").strip()
        
        # Quitar comillas si el usuario arrastró el archivo a la consola de Windows
        ruta = ruta.strip('"').strip("'")
        
        if ruta.lower() == 'salir':
            print("Cerrando el Agente. ¡Hasta luego!")
            break
            
        if not os.path.exists(ruta):
            print(f"❌ El archivo '{ruta}' no existe. Revisa la ruta e intenta de nuevo.")
            continue
            
        print("\nProcesando (esto puede tomar unos segundos)...")
        try:
            # Llamamos a la orquestación central
            respuesta = await ejecutar_agente(ruta)
            
            print("\n================ RESPUESTA ==================")
            print(respuesta)
            print("=============================================\n")
            
        except Exception as e:
            print(f"\n❌ Ocurrió un error en la comunicación: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())