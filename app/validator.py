"""Validação estrita das informações da apólice."""
from .models import PolicyData

def validate_policy(data:dict)->PolicyData:
    return PolicyData.model_validate(data)

def require_minimum(data:PolicyData)->None:
    if not data.minimum_data_present():raise ValueError("Dados mínimos ausentes: empresa/tipo, órgão, concorrência e datas; documento mantido para revisão")
