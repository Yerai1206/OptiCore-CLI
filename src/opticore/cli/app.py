import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from opticore import __version__
from opticore.core.errors import OptiCoreError
from opticore.modules.system import display_rows, snapshot

app = typer.Typer(help="OptiCore · diagnóstico local. Sin comando abre el menú TUI.", no_args_is_help=False)
system = typer.Typer(help="Diagnóstico de solo lectura.")
app.add_typer(system, name="system")
console = Console()


def confirmar(pregunta: str, *, predeterminado: bool = False) -> bool:
    opciones = "S/n" if predeterminado else "s/N"
    respuesta = typer.prompt(f"{pregunta} [{opciones}]", default='', show_default=False).strip().lower()
    return predeterminado if not respuesta else respuesta in {'s', 'si', 'sí', 'y', 'yes'}


@app.command("asistente-ia")
def asistente_ia():
    """Guía paso a paso para usar la API sin escribir rutas ni guardar la clave."""
    from opticore.tui.app import elegir_documento
    from opticore.modules.documents import extract
    from opticore.modules.proveedor_ia import consultar

    typer.echo("Asistente de IA: el texto del documento se enviará al servicio que indiques.")
    typer.echo("Necesitas la URL completa de la API, el nombre del modelo y una clave autorizada.")
    try:
        url = typer.prompt("URL completa de la API (empieza por https://)").strip()
        if not url.lower().startswith("https://"):
            raise OptiCoreError("La dirección debe empezar por https://.")
        modelo = typer.prompt("Nombre del modelo indicado por el centro").strip()
        if not modelo:
            raise OptiCoreError("Necesitas indicar el nombre del modelo.")
        clave = typer.prompt("Clave de API (no aparecerá mientras escribes)", hide_input=True)
        if not clave.strip():
            raise OptiCoreError("Necesitas una clave de API autorizada.")
        certificado = Path.home() / 'Downloads' / 'ca-ies-simarro.crt'
        usar_ca = certificado.is_file() and confirmar("¿Usar el certificado del instituto que está en Descargas?", predeterminado=True)
        typer.echo("Elige el documento en la ventana que se abrirá. Puedes cancelar la selección.")
        archivo = elegir_documento()
        if not archivo:
            typer.echo("Selección cancelada; no se ha enviado nada.")
            return
        tipo = typer.prompt("Elige qué hacer: 1 = resumir; 2 = preguntas", type=int)
        if tipo not in (1, 2):
            raise OptiCoreError("Selecciona 1 o 2.")
        instruccion = ("Resume el documento en español, sin inventar datos." if tipo == 1 else
                       "Crea preguntas de estudio en español basadas únicamente en el documento.")
        texto = extract(Path(archivo))
        typer.echo(f"Se enviará el texto de '{Path(archivo).name}' a: {url}")
        if not confirmar("¿Quieres continuar?"):
            typer.echo("Cancelado; no se ha enviado nada.")
            return
        valores = {'OPTICORE_API_URL': url, 'OPTICORE_AI_MODEL': modelo, 'OPTICORE_API_KEY': clave}
        if usar_ca:
            valores['OPTICORE_CA_FILE'] = str(certificado)
        anteriores = {k: os.environ.get(k) for k in valores}
        try:
            os.environ.update(valores)
            typer.echo("Consultando la IA...")
            typer.echo(consultar(instruccion, texto))
        finally:
            for nombre, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(nombre, None)
                else:
                    os.environ[nombre] = valor
    except (OptiCoreError, OSError, RuntimeError) as exc:
        typer.echo(f"No se pudo completar: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("acciones")
def listar_acciones(config: Annotated[Path | None, typer.Option(help="Archivo de configuración opcional.")] = None):
    """Muestra las acciones disponibles en acciones.json."""
    from opticore.core.configuracion import cargar_acciones
    try:
        for accion in cargar_acciones(config).values():
            typer.echo(f"{accion['id']}: {accion['nombre']}")
    except OptiCoreError as exc:
        typer.echo(f"Error de configuración: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("ejecutar")
def ejecutar_accion(
    identificador: Annotated[str, typer.Argument(help="Identificador de la acción (consulta opticore acciones).")],
    origen: Annotated[Path, typer.Argument(help="Documento o carpeta de entrada.")],
    destino: Annotated[Path | None, typer.Option(help="Archivo Markdown nuevo para la conversión.")] = None,
    config: Annotated[Path | None, typer.Option(help="Archivo acciones.json alternativo.")] = None,
    simular: Annotated[bool, typer.Option(help="Muestra lo que se haría sin escribir ni enviar datos.")] = False,
):
    """Ejecuta una acción configurada. Las acciones con IA envían el texto al proveedor."""
    from opticore.core.configuracion import cargar_acciones
    from opticore.core.motor import ejecutar
    try:
        acciones = cargar_acciones(config)
        if identificador not in acciones:
            raise OptiCoreError(f"Acción '{identificador}' no encontrada. Consulta opticore acciones.")
        typer.echo(ejecutar(acciones[identificador], origen, destino, simular=simular))
    except (OptiCoreError, OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.callback(invoke_without_command=True)
def entry(ctx: typer.Context, version: Annotated[bool, typer.Option("--version")] = False) -> None:
    if version:
        typer.echo(f"OptiCore {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from opticore.tui.app import OptiCoreApp
        OptiCoreApp().run()


@system.command("info")
def info(
    disk: Annotated[Path | None, typer.Option(help="Ruta del volumen a consultar.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Salida estructurada en bytes.")] = False,
) -> None:
    """Muestra SO, procesador, RAM y almacenamiento real."""
    try:
        data = snapshot(disk)
    except OptiCoreError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(json.dumps(data.to_dict(), ensure_ascii=False))
        return
    table = Table(title="OptiCore · System Analyzer")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor")
    for label, value in display_rows(data):
        table.add_row(label, value)
    console.print(table)


from opticore.cli.extended import register
register(app, system)
