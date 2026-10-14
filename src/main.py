"""Consola de la Semana 1: una foto entra y sale la respuesta del agente."""
import asyncio
import json
import os

from src.agent import ejecutar_agente


def _pedir_ruta(mensaje):
    return input(mensaje).strip().strip('"').strip("'")


async def main():
    print("Agente Platica — identificación de piezas")
    print("Escribe 'salir' para terminar.")
    while True:
        ruta = _pedir_ruta("\nRuta de la foto: ")
        if ruta.lower() == "salir":
            break
        if not os.path.isfile(ruta):
            print(f"No existe el archivo: {ruta}")
            continue
        try:
            respuesta = await ejecutar_agente(ruta)
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"No se pudo procesar: {e}")
            continue

        if respuesta.get("estado") == "necesita_otra_foto":
            print(f"\nFalta detalle: {respuesta.get('foto_adicional_solicitada')}")
            segunda = _pedir_ruta("Ruta de la segunda foto (o 'cancelar'): ")
            if segunda.lower() != "cancelar":
                if not os.path.isfile(segunda):
                    print(f"No existe el archivo: {segunda}")
                    continue
                try:
                    respuesta = await ejecutar_agente(ruta, segunda)
                except (FileNotFoundError, ValueError, RuntimeError) as e:
                    print(f"No se pudo procesar la segunda foto: {e}")
                    continue

        print(json.dumps(respuesta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
