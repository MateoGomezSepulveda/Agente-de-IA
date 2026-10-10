import base64
from pathlib import Path

def procesar_imagen_base64(ruta_imagen: str) -> str:
    """
    Lee una imagen local, valida su formato y la convierte a base64 
    lista para enviarse a la API del LLM.
    """
    ruta = Path(ruta_imagen)
    
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró la imagen en: {ruta}")
        
    # Validación estricta de extensiones permitidas por la API de visión
    extensiones_validas = {".jpg", ".jpeg", ".png", ".webp"}
    if ruta.suffix.lower() not in extensiones_validas:
        raise ValueError(f"Formato inválido ({ruta.suffix}). Solo se aceptan: {', '.join(extensiones_validas)}")

    # Conversión a Base64
    with open(ruta, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')

# --- PRUEBA LOCAL ---
if __name__ == "__main__":
    # Probaremos con el archivo test.jpg que descargaste en los pasos anteriores
    ruta_prueba = Path(__file__).resolve().parent.parent / "data" / "fotos_prueba" / "test.jpg"
    
    try:
        resultado_base64 = procesar_imagen_base64(str(ruta_prueba))
        print(f"✅ Imagen procesada exitosamente.")
        print(f"Longitud del texto codificado: {len(resultado_base64)} caracteres.")
    except Exception as e:
        print(f"❌ Error: {e}")