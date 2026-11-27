import json

from typer.testing import CliRunner
from opticore.cli.app import app
from opticore.core.configuracion import cargar_acciones
from opticore.core.motor import ejecutar

runner = CliRunner()


def test_configuracion_incluye_cinco_acciones():
    assert len(cargar_acciones()) >= 5
    assert runner.invoke(app, ['acciones']).exit_code == 0


def test_conversion_simulacion_y_sobrescritura(tmp_path):
    origen = tmp_path / 'origen.txt'
    origen.write_text('Hola mundo', encoding='utf8')
    destino = tmp_path / 'resultado.md'
    accion = cargar_acciones()['convertir']
    assert 'Simulación' in ejecutar(accion, origen, destino, simular=True)
    assert not destino.exists()
    ejecutar(accion, origen, destino)
    assert 'Hola mundo' in destino.read_text(encoding='utf8')
    respuesta = runner.invoke(app, ['ejecutar', 'convertir', str(origen), '--destino', str(destino)])
    assert respuesta.exit_code != 0
    assert 'no se sobrescribe' in respuesta.output
    assert 'Hola mundo' in destino.read_text(encoding='utf8')


def test_config_json_roto(tmp_path):
    config = tmp_path / 'acciones.json'
    config.write_text('{', encoding='utf8')
    resultado = runner.invoke(app, ['acciones', '--config', str(config)])
    assert resultado.exit_code != 0
    assert 'Error de configuración' in resultado.output
    assert 'Traceback' not in resultado.output


def test_config_campos_invalidos(tmp_path):
    config = tmp_path / 'acciones.json'
    config.write_text(json.dumps({'version': 1, 'acciones': [{'id': 'a', 'nombre': 'A', 'tipo': 'ia'}]}), encoding='utf8')
    resultado = runner.invoke(app, ['acciones', '--config', str(config)])
    assert resultado.exit_code != 0
    assert 'instruccion' in resultado.output


def test_documento_inexistente(tmp_path):
    resultado = runner.invoke(app, ['ejecutar', 'tokens', str(tmp_path / 'ausente.txt')])
    assert resultado.exit_code != 0
    assert 'Error:' in resultado.output
    assert 'Traceback' not in resultado.output


def test_sin_clave_ia_no_impide_funciones_locales(tmp_path, monkeypatch):
    for nombre in ('OPTICORE_API_KEY', 'OPTICORE_API_URL', 'OPTICORE_AI_MODEL'):
        monkeypatch.delenv(nombre, raising=False)
    origen = tmp_path / 'texto.txt'
    origen.write_text('Hola mundo', encoding='utf8')
    respuesta = runner.invoke(app, ['ejecutar', 'resumir', str(origen)])
    assert respuesta.exit_code != 0
    assert 'sin conexión' in respuesta.output
    assert runner.invoke(app, ['ejecutar', 'tokens', str(origen)]).exit_code == 0


def test_acciones_ia_usan_su_instruccion(tmp_path, monkeypatch):
    origen = tmp_path / 'texto.txt'
    origen.write_text('Contenido de prueba', encoding='utf8')
    peticiones = []
    def proveedor(instruccion, texto):
        peticiones.append((instruccion, texto))
        return 'Respuesta simulada'
    monkeypatch.setattr('opticore.core.motor.consultar', proveedor)
    for identificador in ('resumir', 'preguntas'):
        resultado = runner.invoke(app, ['ejecutar', identificador, str(origen)])
        assert resultado.exit_code == 0
        assert 'Respuesta simulada' in resultado.output
    assert len(peticiones) == 2
    assert peticiones[0][0] != peticiones[1][0]
    assert all(texto == 'Contenido de prueba' for _, texto in peticiones)


def test_almacenamiento_y_simulacion_ia(tmp_path):
    origen = tmp_path / 'texto.txt'
    origen.write_text('Hola', encoding='utf8')
    analisis = runner.invoke(app, ['ejecutar', 'almacenamiento', str(tmp_path)])
    assert analisis.exit_code == 0
    assert 'Archivos: 1' in analisis.output
    simulacion = runner.invoke(app, ['ejecutar', 'resumir', str(origen), '--simular'])
    assert simulacion.exit_code == 0
    assert 'no se ha enviado nada' in simulacion.output


def test_certificado_inexistente_da_error_controlado(tmp_path, monkeypatch):
    monkeypatch.setenv('OPTICORE_API_KEY', 'clave-de-prueba')
    monkeypatch.setenv('OPTICORE_API_URL', 'https://ejemplo.invalid/v1/chat/completions')
    monkeypatch.setenv('OPTICORE_AI_MODEL', 'modelo-de-prueba')
    monkeypatch.setenv('OPTICORE_CA_FILE', str(tmp_path / 'ausente.crt'))
    origen = tmp_path / 'texto.txt'
    origen.write_text('Prueba', encoding='utf8')
    respuesta = runner.invoke(app, ['ejecutar', 'resumir', str(origen)])
    assert respuesta.exit_code != 0
    assert 'certificado' in respuesta.output
    assert 'Traceback' not in respuesta.output


def test_asistente_ia_pide_confirmacion_y_no_persiste_clave(tmp_path, monkeypatch):
    archivo = tmp_path / 'doc.txt'
    archivo.write_text('Texto de prueba', encoding='utf8')
    monkeypatch.setattr('opticore.tui.app.elegir_documento', lambda: str(archivo))
    llamadas = []
    monkeypatch.setattr('opticore.modules.proveedor_ia.consultar', lambda instruccion, texto: llamadas.append(texto) or 'Respuesta de prueba')
    monkeypatch.delenv('OPTICORE_API_KEY', raising=False)
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    entrada = 'https://ejemplo.invalid/api\nmodelo\nclave-falsa\n1\nn\n'
    resultado = runner.invoke(app, ['asistente-ia'], input=entrada)
    assert resultado.exit_code == 0
    assert not llamadas
    assert 'clave-falsa' not in resultado.output
    entrada = 'https://ejemplo.invalid/api\nmodelo\nclave-falsa\n1\ns\n'
    resultado = runner.invoke(app, ['asistente-ia'], input=entrada)
    assert resultado.exit_code == 0
    assert llamadas == ['Texto de prueba']
    assert 'Respuesta de prueba' in resultado.output
    assert 'clave-falsa' not in resultado.output
    assert 'OPTICORE_API_KEY' not in __import__('os').environ
