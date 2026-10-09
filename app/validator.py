"""Validação semântica mínima e normalização empresarial determinística."""
import unicodedata
from collections.abc import Mapping,Iterable
from .config import settings
from .models import PolicyData

REQUIRED_CONFIDENCE=0.75
LEGAL_SUFFIXES=(
    ("sociedade","limitada"),("s","a"),("ltda",),("limitada",),
    ("eireli",),("epp",),("me",),("sa",),
)

def _company_text(value:str|None)->str:
    if not isinstance(value,str):return ""
    value=value.replace("&"," e ")
    normalized=unicodedata.normalize("NFKD",value.casefold())
    plain="".join(ch for ch in normalized if not unicodedata.combining(ch))
    words=[];current=[]
    for char in plain:
        if char.isalnum():current.append(char)
        elif current:
            words.append("".join(current));current=[]
    if current:words.append("".join(current))
    return " ".join(words)

def _company_core(value:str)->str:
    words=value.split()
    changed=True
    while words and changed:
        changed=False
        for suffix in LEGAL_SUFFIXES:
            if len(words)>=len(suffix) and tuple(words[-len(suffix):])==suffix:
                del words[-len(suffix):];changed=True;break
    return " ".join(words)

def _name_list(value)->list[str]:
    if isinstance(value,str):return [part.strip() for part in value.replace("|",";").split(";") if part.strip()]
    if isinstance(value,Iterable):return [str(part).strip() for part in value if str(part).strip()]
    return []

def _digits(value)->str:
    return "".join(ch for ch in str(value or "") if ch in "0123456789")

def _lot_key(value)->str:
    text=" ".join(str(value or "").casefold().split())
    return text[5:].strip() if text.startswith("lote ") else text

def normalize_company(value,configured_names,cnpj=None,configured_cnpjs=None)->str|None:
    """Mapeia somente nomes/CNPJs configurados; não infere THI/PHAS de nomes arbitrários.

    ``configured_names`` e ``configured_cnpjs`` são dicionários ``{"THI": ..., "PHAS": ...}``.
    Variações de acento, caixa, pontuação e sufixos societários finais são normalizadas
    apenas para comparação. A saída continua sendo exclusivamente THI, PHAS ou None.
    """
    names=configured_names if isinstance(configured_names,Mapping) else {}
    tax_ids=configured_cnpjs if isinstance(configured_cnpjs,Mapping) else {}
    actual_cnpj=_digits(cnpj)
    if actual_cnpj:
        cnpj_matches={code for code in ("THI","PHAS") if any(_digits(item)==actual_cnpj for item in _name_list(tax_ids.get(code)))}
        if len(cnpj_matches)==1:return next(iter(cnpj_matches))
    candidate=_company_text(value)
    if not candidate:return None
    candidate_core=_company_core(candidate)
    matches=set()
    for code in ("THI","PHAS"):
        for alias in _name_list(names.get(code)):
            normalized_alias=_company_text(alias)
            if candidate==normalized_alias or (candidate_core and candidate_core==_company_core(normalized_alias)):
                matches.add(code);break
    return next(iter(matches)) if len(matches)==1 else None

def _settings_company_maps():
    return (
        {"THI":settings.thi_names,"PHAS":settings.phas_names},
        {"THI":settings.thi_cnpj,"PHAS":settings.phas_cnpj},
    )

def validate_policy(data:dict,configured_names=None,configured_cnpjs=None,lote_associado:str|None=None,lotes_associados:list[str]|None=None)->PolicyData:
    """Achata evidências, normaliza empresa antes do Literal e anexa metadado do grupo.

    ``lote`` continua significando exclusivamente lote documental. ``lote_associado``
    é metadado de classificação e nunca cria evidência documental para ``lote``.
    """
    payload=dict(data)
    evidence={}
    for key,value in list(payload.items()):
        if isinstance(value,dict) and {"valor","fonte","confianca"}.issubset(value):
            evidence[key]=value
            payload[key]=value["valor"]
    payload["evidencias"]={**payload.get("evidencias",{}),**evidence}
    structured_lots=payload.get("lotes") or []
    if len(structured_lots)>1:
        # A lista estruturada prevalece; nunca expor um escalar composto/primeiro lote como o único.
        payload["lote"]=None;payload["evidencias"].pop("lote",None)
    # A associação do classificador é metadado operacional. Se a análise apenas
    # ecoou o mesmo identificador sem evidência suficiente, não o rotulamos como
    # lote documental nem inventamos uma evidência para justificá-lo.
    if lote_associado is not None and payload.get("lote") is not None and _lot_key(payload["lote"])==_lot_key(lote_associado):
        lot_evidence=payload["evidencias"].get("lote")
        if not isinstance(lot_evidence,dict) or lot_evidence.get("fonte")=="NAO_IDENTIFICADO" or float(lot_evidence.get("confianca",0) or 0)<REQUIRED_CONFIDENCE:
            payload["lote"]=None;payload["evidencias"].pop("lote",None)
    if configured_names is None or configured_cnpjs is None:
        default_names,default_cnpjs=_settings_company_maps()
        if configured_names is None:configured_names=default_names
        if configured_cnpjs is None:configured_cnpjs=default_cnpjs

    raw_normalized=payload.get("empresa_normalizada")
    raw_company=payload.get("empresa")
    raw_cnpj=payload.get("cnpj")
    cnpj_evidence=payload["evidencias"].get("cnpj",{})
    reliable_cnpj=raw_cnpj if isinstance(cnpj_evidence,dict) and cnpj_evidence.get("fonte")!="NAO_IDENTIFICADO" and float(cnpj_evidence.get("confianca",0) or 0)>=REQUIRED_CONFIDENCE else None
    cnpj_match=normalize_company(None,configured_names,reliable_cnpj,configured_cnpjs) if reliable_cnpj else None
    normalized_match=normalize_company(raw_normalized,configured_names)
    original_match=normalize_company(raw_company,configured_names)
    raw_normalized_label=str(raw_normalized or "").strip().upper()
    raw_type_label=str(payload.get("tipo_empresa") or "").strip().upper()
    # A CNPJ documental configurado prevalece. Sem ele, duas correspondências
    # nominais divergentes são ambíguas e ficam para revisão, nunca se escolhe ao acaso.
    if cnpj_match:
        company_code=cnpj_match;company_evidence=cnpj_evidence
    elif normalized_match and original_match and normalized_match!=original_match:
        company_code=None;company_evidence=None
    elif normalized_match:
        company_code=normalized_match;company_evidence=payload["evidencias"].get("empresa_normalizada")
    elif original_match:
        company_code=original_match;company_evidence=payload["evidencias"].get("empresa")
    else:
        company_code=None;company_evidence=None
    if not cnpj_match and company_code and any(label in {"THI","PHAS"} and label!=company_code for label in (raw_normalized_label,raw_type_label)):
        company_code=None;company_evidence=None
    if company_code and isinstance(company_evidence,dict) and company_evidence.get("fonte")=="NAO_IDENTIFICADO":
        company_code=None;company_evidence=None
    payload["empresa_normalizada"]=company_code
    payload["tipo_empresa"]=company_code
    if company_evidence is not None:
        payload["evidencias"]["empresa_normalizada"]=company_evidence
    if lote_associado is not None:payload["lote_associado"]=lote_associado
    if lotes_associados is not None:payload["lotes_associados"]=list(dict.fromkeys(str(value).strip() for value in lotes_associados if str(value).strip()))
    return PolicyData.model_validate(payload)

def require_minimum(data:PolicyData,lote_associado:str|None=None)->None:
    """Exige evidências nos campos críticos; lote associado não vira campo extraído."""
    if not data.minimum_data_present():
        raise ValueError("Dados mínimos ausentes: empresa normalizada, órgão, concorrência e datas; revisão necessária")
    required=("empresa_normalizada","orgao","numero_concorrencia_normalizado","vigencia_data_inicial","vigencia_data_final")
    missing=[name for name in required if name not in data.evidencias]
    if missing:raise ValueError("Evidência documental ausente nos campos obrigatórios: "+", ".join(missing))
    low=[name for name in required if data.confidence_for(name)<REQUIRED_CONFIDENCE]
    if low:raise ValueError("Confiança insuficiente para publicação nos campos: "+", ".join(low))
    # Só se exige evidência quando a própria extração documental informou um lote.
    # Um lote_associado fornecido pela classificação é metadado operacional independente.
    associated=lote_associado if lote_associado is not None else data.lote_associado
    if associated is not None:data.lote_associado=associated
    if data.lote is not None and associated is not None and _lot_key(data.lote)==_lot_key(associated):
        lot_evidence=data.evidencias.get("lote")
        if lot_evidence is None or lot_evidence.fonte=="NAO_IDENTIFICADO" or lot_evidence.confianca<REQUIRED_CONFIDENCE:
            data.lote=None;data.evidencias.pop("lote",None)
    if data.lote is not None:
        if "lote" not in data.evidencias:raise ValueError("Lote documental identificado sem evidência documental")
        if data.evidencias["lote"].fonte=="NAO_IDENTIFICADO":raise ValueError("Lote documental sem fonte identificada")
        if data.confidence_for("lote")<REQUIRED_CONFIDENCE:raise ValueError("Confiança insuficiente para o lote documental identificado")
    seen_lots=set()
    for index,item in enumerate(data.lotes,1):
        number=item.numero.valor
        if number is None or not str(number).strip():raise ValueError(f"Número ausente no lote estruturado {index}")
        if item.numero.fonte=="NAO_IDENTIFICADO" or item.numero.confianca<REQUIRED_CONFIDENCE:raise ValueError(f"Confiança/fonte insuficiente no número do lote estruturado {index}")
        key=_lot_key(number)
        if key in seen_lots:raise ValueError(f"Lote estruturado duplicado: {number}")
        seen_lots.add(key)
        premium=item.valor_premio
        if premium.valor is not None:
            if premium.fonte=="NAO_IDENTIFICADO" or premium.confianca<REQUIRED_CONFIDENCE:raise ValueError(f"Confiança/fonte insuficiente no prêmio do lote {number}")
            try:amount=float(premium.valor)
            except (TypeError,ValueError) as exc:raise ValueError(f"Prêmio inválido no lote {number}: {premium.valor!r}") from exc
            if amount<0:raise ValueError(f"Prêmio negativo no lote {number}")
    if data.par_coerente is not True:raise ValueError("Apólice e boleto não tiveram coerência confirmada; revisão manual")
