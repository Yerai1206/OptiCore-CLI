import io
import json
from urllib.error import URLError

import pytest

from opticore.modules import proveedor_ia


def preparar(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('OPTICORE_API_URL', 'https://ejemplo.invalid/v1/chat/completions')
    monkeypatch.setenv('OPTICORE_AI_MODEL', 'modelo-prueba')
    monkeypatch.setenv('OPTICORE_API_KEY', 'clave-prueba')
    monkeypatch.delenv('OPTICORE_CA_FILE', raising=False)


def test_proveedor_interpreta_respuesta_sin_red(monkeypatch, tmp_path):
    preparar(monkeypatch, tmp_path)
    llamadas = []
    def servidor_simulado(peticion, *, timeout, context):
        llamadas.append(json.loads(peticion.data))
        assert context.check_hostname and context.verify_mode
        return io.BytesIO(b'{"choices":[{"message":{"content":"Respuesta"}}]}')
    monkeypatch.setattr(proveedor_ia, 'urlopen', servidor_simulado)
    assert proveedor_ia.consultar('Resume', 'Hola') == 'Respuesta'
    assert llamadas[0]['messages'][1]['content'] == 'Hola'


def test_proveedor_sin_red_da_error_sin_filtrar_clave(monkeypatch, tmp_path):
    preparar(monkeypatch, tmp_path)
    def sin_red(*args, **kwargs):
        raise URLError('sin conexión')
    monkeypatch.setattr(proveedor_ia, 'urlopen', sin_red)
    with pytest.raises(proveedor_ia.ErrorIA) as error:
        proveedor_ia.consultar('Resume', 'Hola')
    assert 'clave-prueba' not in str(error.value)
    assert 'conexión' in str(error.value)
