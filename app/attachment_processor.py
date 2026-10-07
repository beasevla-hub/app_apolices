"""Verificação técnica de PDFs e validação conservadora de grupos IA."""
from dataclasses import dataclass
from pathlib import Path
from pypdf import PdfReader

@dataclass
class DocumentGroup:
    lote:str|None
    lote_confianca:float
    apolice:Path|None
    boleto:Path|None
    problema:str|None=None

def valid_pdfs(paths:list[Path])->list[Path]:
    result=[]
    for path in paths:
        try:
            reader=PdfReader(path,strict=False)
            if len(reader.pages)>0 and not reader.is_encrypted:result.append(path)
        except Exception:continue
    return result

def _lot_value(value)->tuple[str|None,float]:
    if isinstance(value,dict):
        raw=value.get("valor");confidence=value.get("confianca",0)
    else:raw=value;confidence=0.0
    lot=str(raw).strip() if raw is not None and str(raw).strip() else None
    try:confidence=max(0.0,min(float(confidence),1.0))
    except (TypeError,ValueError):confidence=0.0
    return lot,confidence

def resolve_groups(result:dict,paths:list[Path])->tuple[list[DocumentGroup],list[str]]:
    """Devolve grupos completos/incompletos e issues, validando nomes e uso único dos PDFs."""
    by_name={p.name:p for p in paths};issues=[]
    raw_groups=result.get("grupos",[]);groups=[];assigned:dict[str,list[int]]={}
    for index,raw in enumerate(raw_groups,1):
        lot_info=raw.get("lote");lot,confidence=_lot_value(lot_info)
        group=DocumentGroup(lot,confidence,None,None)
        if lot and isinstance(lot_info,dict) and lot_info.get("fonte")=="NAO_IDENTIFICADO":group.problema="Lote retornado sem fonte documental identificada"
        for key,attr in (("apolice","apolice"),("boleto","boleto")):
            name=raw.get(key)
            if not name:
                group.problema=f"{key} ausente ou ambíguo no grupo {index}"
                continue
            if name not in by_name:
                group.problema=f"Arquivo {name!r} não corresponde exatamente a um PDF anexado"
                continue
            setattr(group,attr,by_name[name]);assigned.setdefault(name,[]).append(len(groups))
        if not group.apolice or not group.boleto:
            group.problema=group.problema or f"Par incompleto no grupo {index}"
        if lot and confidence<.75:group.problema=group.problema or f"Identificação do lote {lot!r} tem confiança insuficiente"
        groups.append(group)
    duplicated={name for name,indices in assigned.items() if len(indices)>1}
    for name in duplicated:
        issues.append(f"Arquivo {name!r} foi reutilizado em múltiplos grupos; grupos ambíguos")
        for idx in assigned[name]:groups[idx].problema=f"Arquivo compartilhado entre grupos: {name}"
    lot_indices={}
    for idx,group in enumerate(groups):
        if group.lote:
            norm=" ".join(group.lote.casefold().split())
            if norm.startswith("lote "):norm=norm[5:].strip()
            lot_indices.setdefault(norm,[]).append(idx)
    for lot,indices in lot_indices.items():
        if len(indices)>1:
            issues.append(f"Identificador de lote duplicado {lot!r}; grupos ambíguos")
            for idx in indices:groups[idx].problema=f"Identificador de lote duplicado: {lot}"
    raw_others=result.get("outros",[]);others=set()
    for name in raw_others:
        if name not in by_name:issues.append(f"OUTRO {name!r} não corresponde a um arquivo anexado")
        elif name in assigned:
            issues.append(f"Arquivo {name!r} aparece como grupo e OUTRO")
            for idx in assigned[name]:groups[idx].problema=f"Arquivo também classificado como OUTRO: {name}"
        else:others.add(name)
    used=set(assigned)|others
    for name in by_name:
        if name not in used:issues.append(f"Arquivo {name!r} não foi classificado; revisão manual")
    for index,group in enumerate(groups,1):
        if group.problema:issues.append(f"Grupo {index}: {group.problema}")
    return groups,list(dict.fromkeys(issues))
