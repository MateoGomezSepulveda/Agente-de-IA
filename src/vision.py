"""Carga y validación de la foto antes de enviarla al modelo.

La Semana 1 exige rechazar archivos corruptos, formatos no soportados y
archivos demasiado grandes. La reducción de resolución queda para cuando
se mida el costo por tarea (Semana 3); aquí se controla el peso.
"""
import base64
import binascii
from pathlib import Path

EXTENSIONES = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}
MAX_BYTES = 5 * 1024 * 1024
FIRMAS = {
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),
}


def procesar_imagen_base64(ruta_imagen: str) -> str:
    ruta = Path(ruta_imagen)
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontró la imagen: {ruta}")

    formato = EXTENSIONES.get(ruta.suffix.lower())
    if formato is None:
        raise ValueError(
            f"Formato no soportado ({ruta.suffix or 'sin extensión'}). "
            "Se aceptan JPG, PNG y WEBP."
        )

    contenido = ruta.read_bytes()
    if not contenido:
        raise ValueError("La imagen está vacía.")
    if len(contenido) > MAX_BYTES:
        raise ValueError(
            f"La imagen pesa {len(contenido) / 1024 / 1024:.1f} MB y el límite es 5 MB."
        )
    if not contenido.startswith(FIRMAS[formato]):
        raise ValueError("El archivo no coincide con su extensión: parece corrupto o renombrado.")
    if formato == "webp" and contenido[8:12] != b"WEBP":
        raise ValueError("El archivo dice ser WEBP pero no tiene cabecera WEBP.")
    if formato in {"jpeg", "png"} and len(contenido) < 24:
        raise ValueError("La imagen está truncada.")

    try:
        return base64.b64encode(contenido).decode("ascii")
    except binascii.Error as e:
        raise ValueError(f"No se pudo codificar la imagen: {e}") from e
