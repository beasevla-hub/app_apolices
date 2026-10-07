"""Verificação técnica dos PDFs e resolução das classificações da IA."""
from pathlib import Path
from pypdf import PdfReader

def valid_pdfs(paths:list[Path])->list[Path]:
    result=[]
    for path in paths:
        try:
            reader=PdfReader(path,strict=False)
            if len(reader.pages)>0 and not reader.is_encrypted: result.append(path)
        except Exception:continue
    return result

def resolve_roles(result:dict, paths:list[Path])->tuple[Path,Path]:
    roles=result.get("roles",[]); by_name={p.name:p for p in paths}
    policy=[by_name[r["file"]] for r in roles if r.get("file") in by_name and r.get("role")=="APOLICE"]
    bills=[by_name[r["file"]] for r in roles if r.get("file") in by_name and r.get("role")=="BOLETO"]
    if len(policy)!=1 or len(bills)!=1:raise ValueError("Não foi possível identificar exatamente uma apólice e um boleto; revisão manual necessária")
    return policy[0],bills[0]
