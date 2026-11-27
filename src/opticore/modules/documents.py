"""Conversión y selección local de texto, sin llamadas a modelos de IA."""
import hashlib
import os
import re
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

from opticore.core.errors import OptiCoreError

ENCODINGS = {
    "cl100k_base": "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
    "o200k_base": "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
}
CACHE = Path(__file__).parent.parent / "assets" / "tokens"


def tokenizer(name: str = "cl100k_base"):
    if name not in ENCODINGS:
        raise OptiCoreError("Tokenizador admitido: cl100k_base u o200k_base.")
    key = hashlib.sha1(ENCODINGS[name].encode()).hexdigest()
    if not (CACHE / key).is_file():
        raise OptiCoreError("Faltan los datos locales del tokenizador. Ejecuta Preparar OptiCore.cmd.")
    os.environ["TIKTOKEN_CACHE_DIR"] = str(CACHE)
    import tiktoken
    return tiktoken.get_encoding(name)


def count(text: str, encoding: str = "cl100k_base") -> int:
    return len(tokenizer(encoding).encode(text, disallowed_special=()))


def split_blocks(text: str) -> list[str]:
    """Conserva tablas y bloques de código completos durante la selección."""
    blocks, current = [], []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        if not line.strip() and fence is None:
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def extract(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
        raise OptiCoreError("Selecciona un documento de hasta 50 MiB.")
    try:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8-sig")
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise OptiCoreError("PDF cifrado: guarda antes una copia descifrada.")
            if len(reader.pages) > 1000:
                raise OptiCoreError("El límite es 1000 páginas.")
            extracted = [p.extract_text() or "" for p in reader.pages]
            pages = [f"## Página {i}\n\n{text}" for i, text in enumerate(extracted, 1)]
            if not any(text.strip() for text in extracted):
                raise OptiCoreError("El PDF no contiene texto extraíble. Necesita OCR, todavía no incluido.")
            return "\n\n".join(pages)
        if suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                    raise OptiCoreError("DOCX descomprimido demasiado grande.")
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            result = []
            document = Document(path)
            for block in document.iter_inner_content():
                if isinstance(block, Paragraph):
                    text = block.text
                    style = block.style.name if block.style else ""
                    if style.startswith("Heading ") and style[-1:].isdigit():
                        text = "#" * min(int(style[-1]), 6) + " " + text
                    result.append(text)
                elif isinstance(block, Table):
                    rows = [[c.text.replace("|", "\\|").replace("\n", "<br>") for c in row.cells] for row in block.rows]
                    if rows:
                        result.append("\n".join(["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * len(rows[0])) + " |"] + ["| " + " | ".join(r) + " |" for r in rows[1:]]))
            return "\n\n".join(result)
        raise OptiCoreError("Formatos admitidos: TXT UTF-8, Markdown, PDF y DOCX.")
    except OptiCoreError:
        raise
    except Exception as exc:
        raise OptiCoreError(f"No se pudo leer el documento: {exc}") from exc


@dataclass
class DocumentResult:
    source: str
    encoding: str
    original_tokens: int
    output_tokens: int
    omitted_blocks: list[int]
    markdown: str

    def report(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "markdown"}


def convert(path: Path, *, encoding: str = "cl100k_base", budget: int | None = None, query: str = "") -> DocumentResult:
    if budget is not None and budget < 64:
        raise OptiCoreError("El presupuesto mínimo es 64 tokens.")
    original = extract(path)
    if len(original) > 2_000_000:
        raise OptiCoreError("El texto extraído supera el límite de 2 millones de caracteres.")
    original_tokens = count(original, encoding)
    # Sin presupuesto se conserva el contenido. No se suprimen repeticiones automáticamente.
    header = f"<!-- Fuente: {path.name.replace('--', '—')} | Tokenizador: {encoding} -->\n\n"
    omitted = []
    markdown = header + original.rstrip() + "\n"
    if budget is not None and count(markdown, encoding) > budget:
        # Bloques separados por blancos; bloques de código se mantienen íntegros.
        blocks = split_blocks(original)
        if len(blocks) > 5000:
            raise OptiCoreError("Más de 5000 bloques: divide el documento para aplicar un presupuesto.")
        terms = set(re.findall(r"\w+", query.casefold()))
        order = sorted(range(len(blocks)), key=lambda i: (-sum(t in blocks[i].casefold() for t in terms), i))
        selected: set[int] = set()
        def render(indices: set[int]) -> str:
            note = "> AVISO: selección parcial por presupuesto; consulta el original para el contenido omitido.\n\n"
            return header + note + "\n\n".join(f"<!-- Bloque original {i + 1} -->\n{blocks[i]}" for i in sorted(indices)) + "\n"
        for i in order:
            if count(render(selected | {i}), encoding) <= budget:
                selected.add(i)
        markdown = render(selected)
        omitted = [i + 1 for i in range(len(blocks)) if i not in selected]
        if count(markdown, encoding) > budget:
            raise OptiCoreError("El presupuesto no permite incluir los avisos y referencias. Auméntalo.")
    return DocumentResult(str(path.absolute()), encoding, original_tokens, count(markdown, encoding), omitted, markdown)


def save(result: DocumentResult, target: Path) -> None:
    if target.suffix.lower() != ".md":
        raise OptiCoreError("El destino debe terminar en .md.")
    if target.resolve() == Path(result.source).resolve():
        raise OptiCoreError("El destino no puede ser el documento original.")
    # Creación exclusiva: nunca sobreescribir, tampoco a través de un enlace existente.
    with target.open("x", encoding="utf-8") as output:
        output.write(result.markdown)
