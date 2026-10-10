import asyncio
import os
import json
from src.agent import ejecutar_agente

async def main():
    print("==================================================")
    print("🚙 AGENTE DE IA PLATICA - IDENTIFICADOR DE PIEZAS")
    print("==================================================")
    
    while True:
        ruta = input("\n📸 Ruta de la primera imagen (o 'salir'): ").strip().strip('"').strip("'")
        if ruta.lower() == 'salir': break
            
        if not os.path.exists(ruta):
            print(f"❌ Archivo no existe: {ruta}")
            continue
            
        print("\nProcesando primera imagen...")
        respuesta = await ejecutar_agente(ruta)
        
        # INTERCEPTAMOS EL ESTADO
        if isinstance(respuesta, dict) and respuesta.get("estado") == "necesita_otra_foto":
            motivo = respuesta.get('foto_adicional_solicitada', 'Necesito otro ángulo.')
            print(f"\n⚠️ EL AGENTE NECESITA MÁS DETALLES: {motivo}")
            
            ruta_dos = input("📸 Ruta de la segunda imagen (o 'cancelar'): ").strip().strip('"').strip("'")
            if ruta_dos.lower() == 'cancelar':
                continue
                
            if os.path.exists(ruta_dos):
                print("\nProcesando contexto con ambas imágenes...")
                # Llamamos al agente enviándole AMBAS rutas
                respuesta = await ejecutar_agente(ruta, ruta_dos)
            else:
                print(f"❌ Archivo no existe. Abortando consulta.")
                continue
        
        # Mostramos el resultado final
        print("\n================ RESULTADO FINAL =================")
        print(json.dumps(respuesta, indent=2, ensure_ascii=False))
        print("==================================================\n")

if __name__ == "__main__":
    asyncio.run(main())