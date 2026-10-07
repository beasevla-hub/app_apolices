"""Geração determinística e publicação transacional por par documental."""
from pathlib import Path
import os,re,shutil,hashlib
from .models import PolicyData
INVALID=re.compile(r'[<>:"/\\|?*\x00-\x1f]')
def sanitize_filename(name:str)->str:
    value=INVALID.sub("-",str(name)).strip(" .")
    return value[:180] or "documento.pdf"
def sha256(path:Path)->str:
    digest=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()
def lot_label(lot:str|None,unknown_group:str|None=None)->str|None:
    if lot is None:return sanitize_filename(unknown_group) if unknown_group else None
    clean=sanitize_filename(" ".join(str(lot).strip().split())).upper()
    return clean if clean.casefold().startswith("lote") else sanitize_filename("LOTE "+clean)
def build_document_names(data:PolicyData,multiple_lots:bool=False,group_label:str|None=None)->tuple[str,str]:
    org=sanitize_filename(data.orgao_normalizado or data.orgao or "ORGAO")
    number=sanitize_filename(data.numero_concorrencia_normalizado or "CONCORRENCIA-NAO-INFORMADA")
    suffix=lot_label(data.lote,group_label) if multiple_lots else None
    base=sanitize_filename(f"{org} - {number}"+(f" - {suffix}" if suffix else ""))
    return f"01. APOLICE - {base}.pdf",f"08. BOLETO - {base}.pdf"
def build_destination(root:Path,data:PolicyData,multiple_lots:bool=False,group_label:str|None=None)->Path:
    if not data.minimum_data_present():raise ValueError("Dados mínimos ausentes; documentos não publicados")
    if data.empresa_normalizada not in {"THI","PHAS"}:raise ValueError("empresa_normalizada não identificada")
    folder_date=data.vigencia_data_inicial.strftime("%d.%m.%Y")
    org=sanitize_filename(data.orgao_normalizado or data.orgao or "ORGAO")
    number=sanitize_filename(data.numero_concorrencia_normalizado or "")
    destination=Path(root)/data.empresa_normalizada/folder_date/sanitize_filename(f"{org} - {number}")
    suffix=lot_label(data.lote,group_label) if multiple_lots else None
    return destination/suffix if suffix else destination
def publish(root:Path,data:PolicyData,policy:Path,bill:Path,return_created:bool=False,multiple_lots:bool=False,group_label:str|None=None):
    destination=build_destination(root,data,multiple_lots,group_label);destination.mkdir(parents=True,exist_ok=True)
    policy_name,bill_name=build_document_names(data,multiple_lots,group_label)
    pairs=[(Path(policy),destination/policy_name),(Path(bill),destination/bill_name)];created=[]
    try:
        for src,dst in pairs:
            if dst.exists() and sha256(dst)==sha256(src):continue
            if dst.exists():raise FileExistsError(f"Destino já existe com conteúdo diferente: {dst}")
            temp=dst.with_suffix(dst.suffix+".tmp");shutil.copy2(src,temp);os.replace(temp,dst);created.append(dst)
    except Exception:
        for target in created:
            try:target.unlink()
            except OSError:pass
        raise
    return (destination,created) if return_created else destination
