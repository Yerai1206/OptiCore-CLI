import os
import time

import pytest

from opticore.core.errors import OptiCoreError
from opticore.core.state import State
from opticore.modules.cleaner import Cleaner


def test_revisa_solo_temporales_antiguos_y_exige_confirmacion(tmp_path, monkeypatch):
    raiz = tmp_path / 'temporal'
    raiz.mkdir()
    viejo = raiz / 'antiguo.tmp'
    viejo.write_text('basura', encoding='utf8')
    os.utime(viejo, (time.time() - 9 * 86400,) * 2)
    (raiz / 'nuevo.tmp').write_text('nuevo', encoding='utf8')
    (raiz / 'documento.txt').write_text('importante', encoding='utf8')
    cleaner = Cleaner(State(tmp_path / 'estado'), raiz)
    candidatos, _ = cleaner.scan()
    assert [os.path.basename(x.path) for x in candidatos] == ['antiguo.tmp']
    llamadas = []
    monkeypatch.setattr('opticore.modules.cleaner.recycle_file', lambda p: llamadas.append(p))
    with pytest.raises(OptiCoreError):
        cleaner.recycle(candidatos)
    assert not llamadas and viejo.exists()
    assert cleaner.recycle(candidatos, confirmed=True)[0]['status'] == 'papelera'
    assert llamadas == [viejo]


def test_archivo_modificado_se_omite(tmp_path, monkeypatch):
    raiz = tmp_path / 'temporal'
    raiz.mkdir()
    viejo = raiz / 'antiguo.tmp'
    viejo.write_text('antes', encoding='utf8')
    os.utime(viejo, (time.time() - 9 * 86400,) * 2)
    cleaner = Cleaner(State(tmp_path / 'estado'), raiz)
    candidatos, _ = cleaner.scan()
    viejo.write_text('contenido cambiado', encoding='utf8')
    llamadas = []
    monkeypatch.setattr('opticore.modules.cleaner.recycle_file', lambda p: llamadas.append(p))
    assert cleaner.recycle(candidatos, confirmed=True)[0]['status'] == 'omitido'
    assert not llamadas and viejo.exists()
