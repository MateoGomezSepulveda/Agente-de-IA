"""Cliente LLM falso con la misma superficie que AsyncOpenAI.

Permite probar el bucle de tool calling sin créditos ni red. El guion
decide, turno a turno, si el modelo pide una herramienta o responde.
"""
import json
from types import SimpleNamespace


def _mensaje(content=None, tool_calls=None):
    llamadas = None
    if tool_calls:
        llamadas = [
            SimpleNamespace(
                id=f"call_{i}",
                function=SimpleNamespace(
                    name=nombre,
                    arguments=json.dumps(argumentos, ensure_ascii=False),
                ),
            )
            for i, (nombre, argumentos) in enumerate(tool_calls)
        ]
    return SimpleNamespace(content=content, tool_calls=llamadas)


def _respuesta(mensaje):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=mensaje)],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40),
    )


class _Completions:
    def __init__(self, guion):
        self._guion = list(guion)
        self.llamadas = []

    async def create(self, **kwargs):
        self.llamadas.append(kwargs)
        if not self._guion:
            raise RuntimeError("El mock se quedó sin respuestas programadas.")
        paso = self._guion.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return paso


class _Chat:
    def __init__(self, guion):
        self.completions = _Completions(guion)


class ClienteMock:
    """Sustituye a AsyncOpenAI en las pruebas."""

    def __init__(self, guion):
        self.chat = _Chat(guion)

    @staticmethod
    def pedir_tool(nombre, argumentos):
        return _respuesta(_mensaje(tool_calls=[(nombre, argumentos)]))

    @staticmethod
    def responder(contenido):
        if not isinstance(contenido, str):
            contenido = json.dumps(contenido, ensure_ascii=False)
        return _respuesta(_mensaje(content=contenido))
