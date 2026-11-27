# OptiCore CLI

Herramienta para convertir documentos a Markdown, contar tokens y analizar almacenamiento. Incluye un menú interactivo y comandos para automatización. El programa se ha desarrollado con ayuda de IA.

## Instalación

Requisitos: Python 3.12 o superior y pipx. Desde una copia descargada del repositorio:

```powershell
pipx install .
opticore --help
opticore acciones
```

Ejecuta `opticore` sin argumentos para abrir el menú. En Windows puedes usar sus selectores visuales para documentos y carpetas. La conversión de PDF necesita que el PDF contenga texto seleccionable; OCR todavía no está disponible.

En el menú, **PDF a Markdown** permite elegir el PDF con el ratón y guarda un archivo Markdown nuevo junto al original. **Limpiar temporales** busca archivos `.tmp` y `.temp` con al menos siete días dentro de la carpeta temporal del usuario. Puedes revisar la lista, seleccionar archivos y confirmar su envío a la papelera de Windows. Los archivos omitidos se indican; la papelera puede seguir ocupando espacio hasta vaciarse. Ningún archivo se envía a la papelera sin confirmación.

## Ejemplos

```powershell
opticore ejecutar tokens apuntes.pdf
opticore ejecutar convertir apuntes.pdf --destino apuntes.md --simular
opticore ejecutar convertir apuntes.pdf --destino apuntes.md
opticore ejecutar almacenamiento .
opticore ejecutar resumir apuntes.pdf --simular
```

La simulación no crea archivos ni envía información. La conversión crea un archivo nuevo y no sobrescribe uno existente. El contenido extraído de PDF puede perder formato; revísalo.

## Acciones y configuración

Las acciones predeterminadas están en `acciones.json`. Si ejecutas OptiCore desde la carpeta que contiene ese archivo, lo utilizará; en otro caso utilizará la copia incluida en el paquete. También puedes elegir otro archivo con `--config ruta/acciones.json` en `opticore acciones` o `opticore ejecutar`. El documento debe ser un objeto con `version: 1` y una lista no vacía `acciones`. Cada elemento necesita `id` único, `nombre` y `tipo`. Los tipos permitidos son `convertir`, `tokens`, `almacenamiento` e `ia`; para `ia` hay que incluir también `instruccion`. Puedes añadir acciones de IA con instrucciones propias sin cambiar el código. Los demás tipos utilizan operaciones predefinidas; no se ejecuta código arbitrario del JSON.

## IA opcional y privacidad

Para hacerlo paso a paso sin escribir rutas ni guardar la clave, ejecuta `opticore asistente-ia`. El asistente pide la URL completa de la API, el modelo y la clave (oculta al escribir); permite elegir el documento con una ventana y solicita confirmación antes de enviar su texto. La clave se usa solo durante esa ejecución. El nombre de la web del chat no confirma la URL de su API: solicita al centro los datos autorizados.

Las acciones `resumir` y `preguntas` requieren un proveedor compatible con Chat Completions, conexión y las variables `OPTICORE_API_KEY`, `OPTICORE_API_URL` (HTTPS) y `OPTICORE_AI_MODEL`. Copia `.env.example` a `.env` en la carpeta desde la que ejecutes el programa y completa los valores; alternativamente, define variables de entorno. El entorno tiene prioridad. Nunca subas `.env` ni compartas tu clave. Al ejecutar una acción de IA, el texto del documento se envía al proveedor configurado. Las acciones locales funcionan sin clave ni red. Si falta configuración o falla la conexión, se muestra un error y no se modifica el documento. La conexión con un proveedor real aún no se ha verificado.

Para una IA del centro con certificado propio, `OPTICORE_CA_FILE` puede apuntar al certificado CA PEM facilitado y verificado por el instituto. Solo se añade a la verificación TLS de esta aplicación; no se instala en Windows ni se desactiva la verificación del servidor. La dirección de la API, el modelo, la autorización y la conectividad deben ser proporcionados por el centro.

## Estructura del proyecto

El proyecto separa cada responsabilidad por módulos, siguiendo el esquema propuesto en clase:

- `pyproject.toml`: instalación y comando `opticore`.
- `acciones.json`: lista configurable de acciones; el paquete incluye una copia por defecto.
- `src/opticore/cli/`: comandos y opciones con Typer; `src/opticore/tui/` contiene el menú visual.
- `src/opticore/core/configuracion.py`: lectura y validación del JSON.
- `src/opticore/core/motor.py`: ejecuta las acciones admitidas.
- `src/opticore/modules/`: operaciones de documentos, limpieza, sistema y proveedor de IA.
- `src/opticore/core/errors.py`: excepción base; los módulos de configuración e IA incluyen excepciones específicas.
- `docs/adr/0001-configuracion-externa.md`: decisión sobre la configuración externa.
- `tests/` y `.github/workflows/`: pruebas y configuración de GitHub Actions.

## Pruebas

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q tests/test_acciones_config.py tests/test_limpieza_facil.py tests/test_proveedor_ia.py tests/test_mensajes_limpieza.py
```

Las pruebas usan carpetas temporales. La interfaz visual todavía debe verificarse manualmente en un equipo limpio. El proyecto aún necesita publicarse y verificarse en GitHub; no se afirma que haya una release ni un historial previo.
