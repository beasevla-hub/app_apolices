"""Validação semântica mínima dos dados estruturados pela IA."""
from .models import PolicyData

REQUIRED_CONFIDENCE=0.75

def validate_policy(data:dict)->PolicyData:
    payload=dict(data)
    evidence={}
    for key,value in list(payload.items()):
        if isinstance(value,dict) and {"valor","fonte","confianca"}.issubset(value):
            evidence[key]=value
            payload[key]=value["valor"]
    payload["evidencias"]={**payload.get("evidencias",{}),**evidence}
    if payload.get("empresa_normalizada") is None and payload.get("tipo_empresa"):
        payload["empresa_normalizada"]=payload["tipo_empresa"]
    if payload.get("tipo_empresa") is None and payload.get("empresa_normalizada"):
        payload["tipo_empresa"]=payload["empresa_normalizada"]
    return PolicyData.model_validate(payload)

def require_minimum(data:PolicyData)->None:
    if not data.minimum_data_present():
        raise ValueError("Dados mínimos ausentes: empresa normalizada, órgão, concorrência e datas; revisão necessária")
    required=("empresa_normalizada","orgao","numero_concorrencia_normalizado","vigencia_data_inicial","vigencia_data_final")
    missing=[name for name in required if name not in data.evidencias]
    if missing:raise ValueError("Evidência documental ausente nos campos obrigatórios: "+", ".join(missing))
    low=[name for name in required if data.confidence_for(name)<REQUIRED_CONFIDENCE]
    if low:raise ValueError("Confiança insuficiente para publicação nos campos: "+", ".join(low))
