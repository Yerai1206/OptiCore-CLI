"""Interfaz de terminal: los cambios de archivos pasan siempre por servicios."""
import sqlite3
import time
from pathlib import Path
from threading import Event

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, ProgressBar, Select, Static

from opticore.core.errors import OptiCoreError
from opticore.core.state import State
from opticore.modules.cleaner import Cleaner
from opticore.modules.documents import convert, save
from opticore.modules.storage import analyze
from opticore.modules.system import display_rows, snapshot, format_bytes


def elegir_documento() -> str:
    """Abre el selector habitual de Windows y devuelve la ruta elegida."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes('-topmost', True)
        return filedialog.askopenfilename(
            parent=root,
            title='Elige el PDF o documento que quieres convertir',
            filetypes=[('Documentos admitidos', '*.pdf *.docx *.txt *.md'),
                       ('PDF', '*.pdf'), ('Todos los archivos', '*.*')],
        )
    finally:
        root.destroy()


def elegir_carpeta() -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes('-topmost', True)
        return filedialog.askdirectory(parent=root, title='Elige la carpeta que quieres analizar')
    finally:
        root.destroy()


def destino_disponible(source: Path) -> Path:
    """Elige un nombre en la misma carpeta sin reemplazar archivos existentes."""
    target = source.with_suffix('.md')
    number = 1
    while target.exists() or target.is_symlink():
        suffix = ' - convertido' if number == 1 else f' - convertido {number}'
        target = source.with_name(f'{source.stem}{suffix}.md')
        number += 1
    return target


def resumir_limpieza(resultados: list[dict]) -> tuple[str, list[tuple[str, str, str]]]:
    """Resume los resultados y conserva el detalle de los errores."""
    enviados = sum(item.get('status') == 'papelera' for item in resultados)
    omitidos = sum(item.get('status') == 'omitido' for item in resultados)
    simulados = sum(item.get('status') == 'simulado' for item in resultados)
    nombres = {'papelera': 'En papelera', 'omitido': 'No enviado', 'simulado': 'Sin cambios', 'cuarentena': 'En cuarentena'}
    filas = [(nombres.get(item.get('status'), 'Revisar'), Path(item.get('path', '')).name, item.get('error', '')) for item in resultados]
    if simulados:
        mensaje = f'Simulación: {simulados} archivos revisados y ninguno movido. {omitidos} omitidos.'
    else:
        mensaje = f'{enviados} archivos enviados a la papelera; {omitidos} no enviados. La papelera sigue ocupando espacio hasta vaciarse.'
    return mensaje, filas


class Confirm(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancelar")]
    DEFAULT_CSS = """
    Confirm { align: center middle; background: #00000099; }
    Confirm > Vertical { width: 66; height: auto; padding: 2; border: thick #38bfa7; background: #15232d; }
    Confirm Horizontal { height: 3; margin-top: 1; }
    Confirm Button { margin-right: 2; }
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.message, markup=False)
            with Horizontal():
                yield Button("Cancelar", id="no", variant="primary")
                yield Button("Confirmar", id="yes", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)


class OptiCoreApp(App):
    TITLE = "OptiCore"
    SUB_TITLE = "0.1.0 · Herramientas locales"
    BINDINGS = [("ctrl+q", "quit", "Salir"), ("f5", "refresh_system", "Actualizar"), ("escape", "cancel_job", "Cancelar análisis")]
    CSS = """
    Screen { background: #0c141d; color: #dbe8ef; }
    #sidebar { width: 27; background: #13212d; padding: 1; }
    #sidebar Button { width: 100%; margin-bottom: 1; }
    #brand { color: #52dbc0; text-style: bold; margin-bottom: 1; }
    #future { color: #91a7b9; margin-top: 1; }
    #main { width: 1fr; padding: 1 2; }
    #heading { color: #52dbc0; text-style: bold; margin-bottom: 1; }
    #content { border: round #25495c; padding: 1; height: auto; min-height: 5; }
    #form { height: auto; }
    Input, Select { margin-bottom: 1; }
    #actions { height: auto; layout: grid; grid-size: 3; grid-columns: 1fr 1fr 1fr; grid-rows: 3; }
    #actions Button { margin-right: 1; min-width: 8; width: 100%; }
    #table { height: 18; margin-top: 1; }
    #progress { height: 1; margin-top: 1; }
    #status { height: auto; color: #a8bbcb; margin-top: 1; }
    .compact #sidebar { width: 21; padding: 0 1; }
    .compact #sidebar Button { margin-bottom: 0; }
    .compact #main { padding: 0 1; }
    .compact #table { height: 12; }
    """

    def __init__(self):
        super().__init__()
        self.view = "dashboard"
        self.busy = False
        self.cancel = Event()
        self.candidates = []
        self.selected: set[int] = set()
        self.move_rows = []
        self.state: State | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with VerticalScroll(id="sidebar"):
                yield Static("◈ OPTICORE\nTu equipo, con claridad.", id="brand")
                for key, label in [("dashboard", "Inicio"), ("documents", "PDF a Markdown"), ("clean", "Limpiar temporales"), ("assistant-ai", "Asistente IA"), ("history", "Historial"), ("exit", "Salir")]:
                    yield Button(label, id=key, variant="primary" if key == "dashboard" else "default")
                yield Static("Elige una opción. Usa Tab para moverte y Enter para seleccionar.", id="future")
            with VerticalScroll(id="main"):
                yield Static("Inicio", id="heading")
                yield Static("Consultando el sistema…", id="content", markup=False)
                with Vertical(id="form"):
                    yield Button("Elegir PDF o documento...", id="choose-document", variant="primary")
                    yield Button("Elegir carpeta...", id="choose-folder", variant="primary")
                    yield Static("Todavía no has elegido ningún archivo o carpeta.", id="selection", markup=False)
                    yield Input(placeholder="Ruta de la carpeta o del archivo de origen", id="path")
                    yield Input(placeholder="Ruta del nuevo archivo .md, por ejemplo C:\\Notas\\resultado.md", id="output")
                    yield Input(placeholder="Límite de tokens (opcional; mínimo 64)", id="budget", type="integer")
                    yield Input(placeholder="Tema que quieres priorizar (opcional)", id="query")
                    yield Select([("cl100k_base · GPT-4 / GPT-3.5", "cl100k_base"), ("o200k_base · familia GPT-4o", "o200k_base")], value="cl100k_base", allow_blank=False, id="encoding")
                    yield Input(placeholder="Antigüedad mínima en días (7–3650)", id="days", type="integer")
                with Horizontal(id="actions"):
                    for key, label in [("run", "Actualizar"), ("cancel", "Cancelar"), ("simulate", "Simular"), ("select-all", "Elegir todos"), ("recycle", "Enviar a papelera"), ("apply", "Cuarentena"), ("quarantine", "Ver cuarentena"), ("restore", "Restaurar")]:
                        yield Button(label, id=key, variant="success" if key == "run" else "default")
                yield ProgressBar(total=100, show_eta=False, id="progress")
                yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
                yield Static("Todo se procesa en este equipo.", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.state = State()
        except (OSError, sqlite3.Error) as exc:
            self.query_one("#status", Static).update(f"No se puede abrir el historial: {exc}")
        self.switch("dashboard")
        self.set_interval(2, self.monitor_tick)

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 100, "compact")

    def monitor_tick(self) -> None:
        if self.view == "system" and not self.busy and len(self.screen_stack) == 1:
            self.start_job("load")

    def switch(self, view: str) -> None:
        self.view = view
        self.sub_title = "Herramientas para tu ordenador"
        labels = {"dashboard": "Inicio", "system": "Sistema", "disk": "Analizar almacenamiento", "clean": "Limpiar temporales", "documents": "Convertir a Markdown", "history": "Historial de operaciones", "settings": "Configuración", "quarantine_view": "Cuarentena recuperable"}
        self.query_one("#heading", Static).update(labels[view])
        for button in self.query('#sidebar Button'):
            button.variant = 'primary' if button.id == view else 'default'
        for widget in self.query("#form Input, #form Select"):
            widget.display = False
        self.query_one("#choose-document", Button).display = view == "documents"
        self.query_one("#choose-folder", Button).display = view == "disk"
        self.query_one("#selection", Static).display = view in {"disk", "documents"}
        self.query_one("#selection", Static).update("Todavía no has elegido ningún archivo o carpeta.")
        self.query_one("#path", Input).value = ""
        self.query_one("#output", Input).value = ""
        for key in ["run", "cancel", "simulate", "select-all", "recycle", "apply", "quarantine", "restore"]:
            self.query_one(f"#{key}", Button).display = False
        self.query_one("#run", Button).display = view not in {"quarantine_view", "dashboard"}
        self.query_one("#run", Button).label = {"disk": "Analizar", "clean": "Escanear", "documents": "Convertir", "settings": "Guardar"}.get(view, "Actualizar")
        self.query_one("#table", DataTable).display = view not in {"dashboard", "system", "settings"}
        self.query_one("#table", DataTable).clear(columns=True)
        self.query_one("#progress", ProgressBar).display = False
        notes = {
            "dashboard": "Bienvenido a OptiCore. Elige PDF a Markdown para convertir documentos o Limpiar temporales para revisar archivos antiguos. Usa el ratón o Tab y Enter.",
            "system": "Consulta el uso del procesador, la memoria y el espacio del disco. Se actualiza automáticamente cada dos segundos y no modifica nada.",
            "disk": "1. Pulsa «Elegir carpeta» y selecciónala con el ratón. 2. Pulsa «Analizar». Verás los archivos y carpetas que más ocupan. No se borra nada.",
            "clean": "1. Pulsa Escanear. 2. Revisa la lista y selecciona archivos con Enter o pulsa Elegir todos. 3. Pulsa Enviar a papelera y confirma. Solo se buscan archivos .tmp y .temp con al menos 7 días. La papelera puede seguir ocupando espacio hasta vaciarse.",
            "documents": "1. Pulsa «Elegir PDF o documento» y selecciónalo en la ventana. 2. Pulsa «Convertir». El archivo Markdown se guardará junto al original con un nombre disponible. También puedes convertir Word o texto. Los PDF escaneados necesitan OCR y las tablas pueden perder formato.",
            "history": "Consulta las operaciones guardadas en este ordenador. El historial puede incluir rutas de tus archivos.",
            "settings": "Cambia la antigüedad mínima de los archivos temporales y el contador de tokens. Pulsa Guardar para conservar tus preferencias. No cambia ajustes de Windows.",
            "quarantine_view": "Aquí aparecen los archivos movidos a cuarentena. Selecciona una operación, pulsa Restaurar y confirma. No se sobrescribe ningún archivo existente.",
        }
        self.query_one("#content", Static).update(notes[view])
        mensajes = {'dashboard': 'Elige una herramienta del menú para comenzar.',
                    'documents': 'Paso 1: elige un documento.',
                    'clean': 'Paso 1: pulsa Escanear para revisar los archivos temporales.',
                    'history': 'Consultando el historial.', 'quarantine_view': 'Consultando la cuarentena.'}
        self.query_one('#status', Static).update(mensajes.get(view, 'Elige una opción para continuar.'))
        # Las rutas son internas: la selección se hace mediante ventanas.
        if view == "settings":
            self.query_one("#days", Input).display = True
            self.query_one("#encoding", Select).display = True
            if self.state:
                self.query_one("#days", Input).value = str(self.state.get("clean_days", 7))
        if self.state and view in {"documents", "settings"}:
            self.query_one("#encoding", Select).value = self.state.get("encoding", "cl100k_base")
        if view == "clean":
            self.candidates = []
            self.selected.clear()
            for key in ["simulate", "select-all", "recycle", "quarantine"]:
                self.query_one(f"#{key}", Button).display = True
        if view == "quarantine_view":
            self.query_one("#restore", Button).display = True
        if view in {"system", "history", "quarantine_view"}:
            self.start_job("load")

    def set_table(self, columns, rows) -> None:
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns(*columns)
        for row in rows:
            table.add_row(*(str(v) for v in row))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        key = event.button.id
        if key == "exit":
            self.cancel.set()
            self.exit()
        elif key == "cancel":
            self.action_cancel_job()
        elif self.busy:
            return
        elif key == "assistant-ai":
            from opticore.cli.app import asistente_ia
            import typer
            with self.suspend():
                try:
                    asistente_ia()
                except (typer.Exit, typer.Abort, KeyboardInterrupt, EOFError):
                    pass
                try:
                    input("\nPulsa Intro para volver a OptiCore...")
                except EOFError:
                    pass
        elif key == "choose-document":
            try:
                chosen = elegir_documento()
                if chosen:
                    source = Path(chosen)
                    destino = destino_disponible(source)
                    self.query_one("#path", Input).value = str(source)
                    self.query_one("#output", Input).value = str(destino)
                    self.query_one("#selection", Static).update(f"Documento elegido: {source.name}\nSe guardará junto al original como: {destino.name}")
                    self.query_one("#budget", Input).value = ""
                    self.query_one("#query", Input).value = ""
                    self.query_one("#status", Static).update("Documento seleccionado. Pulsa Convertir para guardar el Markdown.")
                else:
                    self.query_one("#status", Static).update("Selección cancelada. Puedes volver a elegir un documento.")
            except Exception as exc:
                self.query_one("#status", Static).update(f"No se pudo abrir el selector de archivos: {exc}")
        elif key == "choose-folder":
            try:
                chosen = elegir_carpeta()
                if chosen:
                    self.query_one("#path", Input).value = chosen
                    self.query_one("#selection", Static).update(f"Carpeta elegida: {Path(chosen).name or chosen}")
                    self.query_one("#status", Static).update("Carpeta seleccionada. Pulsa Analizar.")
                else:
                    self.query_one("#status", Static).update("Selección cancelada. Puedes elegir una carpeta cuando quieras.")
            except Exception as exc:
                self.query_one("#status", Static).update(f"No se pudo abrir el selector de carpetas: {exc}")
        elif key in {"dashboard", "system", "disk", "clean", "documents", "history", "settings"}:
            self.switch(key)
        elif key == "quarantine":
            self.switch("quarantine_view")
        elif key == "select-all":
            if not self.candidates:
                self.notify('No hay archivos en la lista. Pulsa Escanear primero.')
                return
            self.selected = set(range(len(self.candidates)))
            table = self.query_one('#table', DataTable)
            for row in self.selected:
                table.update_cell_at((row, 0), 'V')
            self.query_one('#status', Static).update(f'{len(self.selected)} archivos seleccionados. Revisa la lista antes de continuar.')
        elif key == "recycle":
            if not self.selected:
                self.notify('Primero escanea y selecciona archivos.')
                return
            size = sum(self.candidates[i].size for i in self.selected)
            self.push_screen(Confirm(f'¿Enviar {len(self.selected)} archivos ({format_bytes(size)}) a la papelera?\nPuedes revisarlos allí antes de vaciarla.'), lambda yes: self.start_job('recycle') if yes else None)
        elif key == "apply":
            if not self.selected:
                self.notify("Selecciona archivos con Enter.")
                return
            size = sum(self.candidates[i].size for i in self.selected)
            self.push_screen(Confirm(f"¿Mover {len(self.selected)} archivos ({format_bytes(size)}) a cuarentena?\nNo libera espacio en el disco."), lambda yes: self.start_job("apply") if yes else None)
        elif key == "restore":
            row = self.query_one("#table", DataTable).cursor_row
            if row < len(self.move_rows):
                operation = self.move_rows[row]["id"]
                self.push_screen(Confirm(f"¿Restaurar la operación {operation}?"), lambda yes: self.start_job("restore", operation) if yes else None)
        else:
            self.start_job("simulate" if key == "simulate" else "run")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self.view == "clean" and not self.busy:
            row = event.cursor_row
            if row < len(self.candidates):
                if row in self.selected:
                    self.selected.remove(row)
                else:
                    self.selected.add(row)
                event.data_table.update_cell_at((row, 0), "✓" if row in self.selected else "·")
                self.query_one("#status", Static).update(f"{len(self.selected)} seleccionados · {format_bytes(sum(self.candidates[i].size for i in self.selected))}")

    def action_refresh_system(self) -> None:
        if not self.busy:
            self.start_job("run")

    def action_cancel_job(self) -> None:
        self.cancel.set()
        self.query_one("#status", Static).update("Cancelación solicitada; esperando un punto seguro…")

    def start_job(self, action: str, operation: int | None = None) -> None:
        if self.busy:
            return
        if self.view == 'documents' and not self.query_one('#path', Input).value.strip():
            self.query_one('#status', Static).update('Primero pulsa Elegir PDF o documento y selecciona un archivo.')
            self.notify('Primero elige un documento.')
            return
        self.busy = True
        self.cancel = Event()
        values = {key: self.query_one(f"#{key}", Input).value for key in ["path", "output", "budget", "query", "days"]}
        values["encoding"] = str(self.query_one("#encoding", Select).value)
        for button in self.query(Button):
            button.disabled = button.id not in {"cancel", "exit"}
        self.query_one("#cancel", Button).display = True
        self.query_one("#progress", ProgressBar).display = True
        self.query_one("#progress", ProgressBar).update(total=None, progress=0)
        self.query_one("#status", Static).update("Procesando localmente…")
        self.run_job(self.view, action, values, operation)

    @work(thread=True, exclusive=True)
    def run_job(self, view: str, action: str, values: dict, operation: int | None) -> None:
        result = None
        error = None
        last_progress = 0.0
        def progress(entries: int) -> None:
            nonlocal last_progress
            now = time.monotonic()
            if now - last_progress >= 0.25:
                last_progress = now
                self.call_from_thread(self.show_progress, entries)
        try:
            state = self.state
            if view in {"dashboard", "system"}:
                result = snapshot()
            elif state is None:
                raise OptiCoreError("El almacenamiento local no está disponible.")
            elif view == "disk":
                if not values["path"].strip():
                    raise OptiCoreError("Primero pulsa «Elegir carpeta» y selecciona una carpeta.")
                result = analyze(Path(values["path"].strip().strip('"')), self.cancel, progress)
                state.log("disk.analyze", {"root": result.root, "bytes": result.bytes, "files": result.files, "partial": result.partial})
            elif view == "clean":
                cleaner = Cleaner(state)
                if action in {"simulate", "apply", "recycle"}:
                    if not self.selected:
                        raise OptiCoreError("Selecciona al menos un archivo con Enter.")
                    selected = [self.candidates[i] for i in sorted(self.selected)]
                    result = cleaner.recycle(selected, confirmed=True) if action == 'recycle' else cleaner.apply(selected, confirmed=action == "apply", dry_run=action != "apply")
                else:
                    result = cleaner.scan(state.get("clean_days", 7), self.cancel, progress)
            elif view == "quarantine_view":
                cleaner = Cleaner(state)
                if action == "restore":
                    cleaner.restore(operation, confirmed=True)
                result = cleaner.moves()
            elif view == "documents":
                if not values["path"].strip() or not values["output"].strip():
                    raise OptiCoreError("Primero pulsa «Elegir PDF o documento» y selecciona un archivo.")
                budget = int(values["budget"]) if values["budget"] else None
                result = convert(Path(values["path"].strip().strip('"')), encoding=values["encoding"], budget=budget, query=values["query"])
                if self.cancel.is_set():
                    raise OptiCoreError("Cancelado antes de guardar.")
                try:
                    save(result, Path(values["output"].strip().strip('"')))
                except FileExistsError as exc:
                    raise OptiCoreError('El archivo de destino ya existe. Vuelve a elegir el documento para generar otro nombre sin sobrescribirlo.') from exc
                state.log("ai.convert", {**result.report(), "output": values["output"]})
            elif view == "history":
                result = state.history()
            elif view == "settings":
                days = int(values["days"])
                if not 7 <= days <= 3650:
                    raise OptiCoreError("Antigüedad admitida: entre 7 y 3650 días.")
                state.set("clean_days", days)
                state.set("encoding", values["encoding"])
        except Exception as exc:
            error = str(exc)
        self.call_from_thread(self.finish_job, view, action, result, error)

    def show_progress(self, entries: int) -> None:
        self.query_one("#status", Static).update(f"{entries:,} entradas revisadas · Escape para cancelar")

    def finish_job(self, view, action, result, error) -> None:
        self.busy = False
        for button in self.query(Button):
            button.disabled = False
        self.query_one("#cancel", Button).display = False
        self.query_one("#progress", ProgressBar).display = False
        self.query_one("#progress", ProgressBar).update(total=100, progress=100 if not error else 0)
        if error:
            self.query_one("#status", Static).update(f"Error: {error}")
            self.notify(error, severity="error")
            return
        message = "Operación terminada."
        if view in {"dashboard", "system"}:
            self.query_one("#content", Static).update("ESTADO DEL ORDENADOR (elige una opción del menú para continuar)\n\n" + "\n".join(f"{k}: {v}" for k, v in display_rows(result)))
        elif view == "disk":
            rows = [("Carpeta", format_bytes(size), name) for name, size in sorted(result.folders.items(), key=lambda r: r[1], reverse=True)]
            rows += [("Archivo", format_bytes(size), path) for size, path in result.largest]
            self.set_table(["Tipo", "Tamaño lógico", "Ruta"], rows)
            message = f"{result.files:,} archivos · {format_bytes(result.bytes)} · {result.skipped} omitidos · {'PARCIAL' if result.partial else 'Completo'}"
            if result.warnings:
                message += "\n" + "\n".join(result.warnings)
        elif view == "clean":
            if action in {"simulate", "apply", "recycle"}:
                message, rows = resumir_limpieza(result)
                if action != 'simulate':
                    self.query_one("#content", Static).update('Resultado de la limpieza. Puedes volver a escanear para buscar más archivos.')
                    self.set_table(['Resultado', 'Archivo', 'Detalle'], rows)
                if action in {"apply", "recycle"}:
                    self.selected.clear()
                    self.candidates = []
            else:
                self.candidates, report = result
                self.selected.clear()
                self.set_table(["Elegir", "Tamaño", "Archivo"], [("·", format_bytes(c.size), c.path) for c in self.candidates])
                message = (f"{len(self.candidates)} archivos encontrados · {format_bytes(sum(c.size for c in self.candidates))}. "
                           + ('Algunos archivos no se pudieron revisar. ' if report.partial or report.skipped else '')
                           + ('Elige archivos con Enter o pulsa Elegir todos.' if self.candidates else 'No se encontraron temporales antiguos.'))
        elif view == "quarantine_view":
            self.move_rows = result
            self.set_table(["ID", "Estado", "Origen"], [(r["id"], r["status"], r["source"]) for r in result])
        elif view == "documents":
            self.set_table(["Métrica", "Valor"], [("Tokens del texto extraído", result.original_tokens), ("Tokens Markdown generado", result.output_tokens), ("Diferencia", result.output_tokens - result.original_tokens), ("Tokenizador", result.encoding), ("Bloques omitidos", ", ".join(map(str, result.omitted_blocks)) or "Ninguno")])
            self.query_one("#content", Static).update(result.markdown[:6000] + ("\n[Vista previa limitada a 6000 caracteres]" if len(result.markdown) > 6000 else ""))
            message = f"Markdown guardado en: {self.query_one('#output', Input).value}. " + ("AVISO: hay contenido omitido; revisa el original." if result.omitted_blocks else "Revisa el resultado, especialmente las tablas del PDF.")
        elif view == "history":
            self.set_table(["Fecha UTC", "Operación", "Detalle"], [(r["created"], r["kind"], r["detail"]) for r in result])
        elif view == "settings":
            message = f"Preferencias guardadas · Datos locales: {self.state.folder}"
        self.query_one("#status", Static).update(message)
