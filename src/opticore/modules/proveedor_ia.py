"""Proveedor opcional compatible con el formato Chat Completions."""
import json
import os
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from opticore.core.errors import OptiCoreError


class ErrorIA(OptiCoreError):
    pass


def cargar_entorno(ruta: Path = Path('.env')) -> None:
    """Lee solo las tres variables admitidas sin sustituir el entorno existente."""
    if not ruta.is_file():
        return
    try:
        for linea in ruta.read_text(encoding='utf-8-sig').splitlines():
            linea = linea.strip()
            if not linea or linea.startswith('#') or '=' not in linea:
                continue
            nombre, valor = linea.split('=', 1)
            nombre = nombre.strip()
            if nombre in {'OPTICORE_API_KEY', 'OPTICORE_API_URL', 'OPTICORE_AI_MODEL', 'OPTICORE_CA_FILE'}:
                os.environ.setdefault(nombre, valor.strip().strip('"').strip("'"))
    except (OSError, UnicodeError) as exc:
        raise ErrorIA('No se pudo leer el archivo .env. Comprueba que sea texto UTF-8.') from exc


def consultar(instruccion: str, texto: str) -> str:
    cargar_entorno()
    clave = os.environ.get("OPTICORE_API_KEY")
    url = os.environ.get("OPTICORE_API_URL")
    modelo = os.environ.get("OPTICORE_AI_MODEL")
    if not clave or not url or not modelo:
        raise ErrorIA("Para usar IA configura OPTICORE_API_KEY, OPTICORE_API_URL y OPTICORE_AI_MODEL. Las demás acciones funcionan sin conexión.")
    if not url.startswith("https://"):
        raise ErrorIA("OPTICORE_API_URL debe usar HTTPS.")
    if len(texto) > 100_000:
        raise ErrorIA("El texto supera 100.000 caracteres; divide el documento antes de enviarlo.")
    ca_file = os.environ.get("OPTICORE_CA_FILE")
    try:
        contexto = ssl.create_default_context()
        if ca_file:
            contexto.load_verify_locations(cafile=ca_file)
    except (OSError, ssl.SSLError) as exc:
        raise ErrorIA("No se pudo leer el certificado indicado en OPTICORE_CA_FILE. Comprueba el archivo facilitado por el centro.") from exc
    carga = json.dumps({"model": modelo, "messages": [{"role": "system", "content": instruccion}, {"role": "user", "content": texto}]}).encode("utf-8")
    peticion = Request(url, data=carga, headers={"Authorization": "Bearer " + clave, "Content-Type": "application/json"})
    try:
        with urlopen(peticion, timeout=30, context=contexto) as respuesta:
            datos = json.load(respuesta)
        return datos["choices"][0]["message"]["content"]
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError, IndexError, OSError) as exc:
        raise ErrorIA("No se pudo obtener una respuesta de IA. Comprueba conexión y configuración; las funciones locales siguen disponibles.") from exc
