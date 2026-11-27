"""Ejecuta las operaciones sin interpretar comandos arbitrarios de la configuración."""
from pathlib import Path

from opticore.core.errors import OptiCoreError
from opticore.modules.documents import convert, count, extract, save
from opticore.modules.storage import analyze
from opticore.modules.proveedor_ia import consultar


def ejecutar(accion: dict, origen: Path, destino: Path | None = None, *, simular: bool = False) -> str:
    tipo = accion["tipo"]
    if tipo == "almacenamiento":
        resultado = analyze(origen)
        return f"Archivos: {resultado.files}; bytes: {resultado.bytes}; omitidos: {resultado.skipped}; parcial: {resultado.partial}"
    if tipo == "tokens":
        return f"Tokens del texto extraído: {count(extract(origen))} (cl100k_base)"
    if tipo == "ia":
        if simular:
            return f"Simulación: se enviaría el texto de {origen.name} al proveedor configurado; no se ha enviado nada."
        return consultar(accion["instruccion"], extract(origen))
    if tipo == "convertir":
        if destino is None:
            raise OptiCoreError("Indica un archivo de destino con --destino.")
        if destino.suffix.lower() != ".md" or destino.exists():
            raise OptiCoreError("El destino debe ser un archivo .md nuevo; no se sobrescribe ningún archivo.")
        resultado = convert(origen)
        if simular:
            return f"Simulación: se convertiría {origen.name} a {destino.name}; no se ha creado ningún archivo."
        save(resultado, destino)
        return f"Archivo creado: {destino}; tokens: {resultado.output_tokens}."
    raise OptiCoreError("Tipo de acción no admitido.")
