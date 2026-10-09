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
    lotes:list[tuple[str,float]]|None=None

    @property
    def valores_lotes(self)->list[str]:
        if self.lotes:return [value for value,_ in self.lotes]
        return [self.lote] if self.lote is not None else []

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

def _normalize_lot(value:str)->str:
    text=" ".join(value.casefold().split())
    return text[5:].strip() if text.startswith("lote ") else text

def _looks_like_compound_lot(value:str)->bool:
    text=" "+" ".join(value.casefold().split())+" "
    return any(separator in text for separator in (" e "," and ",",","/"))

def resolve_groups(result:dict,paths:list[Path])->tuple[list[DocumentGroup],list[str]]:
    """Devolve grupos completos/incompletos e issues, validando nomes e uso único dos PDFs."""
    by_name={p.name:p for p in paths};issues=[]
    raw_groups=result.get("grupos",[]);groups=[];assigned:dict[str,list[int]]={}
    for index,raw in enumerate(raw_groups,1):
        lot_info=raw.get("lote");raw_lots=raw.get("lotes")
        if isinstance(raw_lots,list) and raw_lots:
            lot_items=[_lot_value(item) for item in raw_lots]
            lots=[(value,confidence) for value,confidence in lot_items if value is not None]
        else:
            lot,confidence=_lot_value(lot_info)
            lots=[(lot,confidence)] if lot is not None else []
        group=DocumentGroup(lots[0][0] if len(lots)==1 else None,lots[0][1] if len(lots)==1 else 0.0,None,None,lotes=lots)
        if not (isinstance(raw_lots,list) and raw_lots) and lot is not None and _looks_like_compound_lot(lot):
            group.problema="Lote retornado como texto composto/ambíguo; exige lista estruturada"
        for raw_item,(value,confidence) in zip(raw_lots if isinstance(raw_lots,list) and raw_lots else [lot_info],lot_items if isinstance(raw_lots,list) and raw_lots else ([(lot,confidence)] if lot is not None else [])):
            if value and isinstance(raw_item,dict) and raw_item.get("fonte")=="NAO_IDENTIFICADO":group.problema=group.problema or "Lote retornado sem fonte documental identificada"
            if value and confidence<.75:group.problema=group.problema or f"Identificação do lote {value!r} tem confiança insuficiente"
        normalized=[_normalize_lot(value) for value,_ in lots]
        if len(normalized)!=len(set(normalized)):group.problema=group.problema or "A lista do grupo contém lotes duplicados"
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
        groups.append(group)
    duplicated={name for name,indices in assigned.items() if len(indices)>1}
    for name in duplicated:
        issues.append(f"Arquivo {name!r} foi reutilizado em múltiplos grupos; grupos ambíguos")
        for idx in assigned[name]:groups[idx].problema=f"Arquivo compartilhado entre grupos: {name}"
    lot_indices={}
    for idx,group in enumerate(groups):
        for value in group.valores_lotes:
            lot_indices.setdefault(_normalize_lot(value),[]).append(idx)
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
