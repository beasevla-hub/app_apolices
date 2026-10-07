"""Preparação das páginas iniciais da apólice sem alterar original."""
from pathlib import Path
from pypdf import PdfReader,PdfWriter

def first_pages(source:Path,destination:Path,count:int=3)->Path:
    reader=PdfReader(source,strict=False)
    if reader.is_encrypted or not reader.pages:raise ValueError(f"PDF vazio, inválido ou criptografado: {source.name}")
    writer=PdfWriter()
    for page in reader.pages[:count]:writer.add_page(page)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open("wb") as handle:writer.write(handle)
    return destination
