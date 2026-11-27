from opticore.tui.app import resumir_limpieza


def test_resultados_muestran_aciertos_y_errores():
    mensaje, filas = resumir_limpieza([
        {'status': 'papelera', 'path': 'primero.tmp'},
        {'status': 'omitido', 'path': 'segundo.tmp', 'error': 'El archivo está en uso'},
    ])
    assert '1 archivos enviados' in mensaje
    assert '1 no enviados' in mensaje
    assert filas == [('En papelera', 'primero.tmp', ''), ('No enviado', 'segundo.tmp', 'El archivo está en uso')]


def test_simulacion_indica_que_no_hubo_cambios():
    mensaje, filas = resumir_limpieza([{'status': 'simulado', 'path': 'prueba.tmp'}])
    assert 'ninguno movido' in mensaje
    assert filas[0][0] == 'Sin cambios'
