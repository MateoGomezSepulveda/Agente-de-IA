import pytest

from src.vision import procesar_imagen_base64


def test_jpg_de_prueba_se_codifica():
    codificada = procesar_imagen_base64("data/fotos_prueba/test.jpg")
    assert codificada.startswith("/9j/")


def test_archivo_inexistente():
    with pytest.raises(FileNotFoundError):
        procesar_imagen_base64("data/fotos_prueba/no_existe.jpg")


def test_formato_no_soportado(tmp_path):
    archivo = tmp_path / "pieza.gif"
    archivo.write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="no soportado"):
        procesar_imagen_base64(archivo)


def test_archivo_corrupto_o_renombrado(tmp_path):
    archivo = tmp_path / "pieza.jpg"
    archivo.write_bytes(b"esto no es una imagen")
    with pytest.raises(ValueError, match="corrupto"):
        procesar_imagen_base64(archivo)


def test_archivo_demasiado_grande(tmp_path):
    archivo = tmp_path / "pieza.jpg"
    archivo.write_bytes(b"\xff\xd8\xff" + b"x" * (5 * 1024 * 1024))
    with pytest.raises(ValueError, match="límite"):
        procesar_imagen_base64(archivo)
