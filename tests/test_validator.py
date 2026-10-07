import pytest
from app.validator import validate_policy,require_minimum

def result(confidence=.9):
    fields={'empresa_normalizada':'THI','orgao':'Órgão','numero_concorrencia_normalizado':'10-2026','vigencia_data_inicial':'2026-08-01','vigencia_data_final':'2027-08-01'}
    data={key:{'valor':value,'fonte':'APOLICE','confianca':confidence} for key,value in fields.items()}
    data['confianca_geral']=.99;return data

def test_validator_accepts_high_confidence_with_evidence():require_minimum(validate_policy(result()))
def test_validator_rejects_low_confidence_and_missing_evidence():
    with pytest.raises(ValueError,match='Confiança insuficiente'):require_minimum(validate_policy(result(.3)))
    data=result();del data['orgao']
    with pytest.raises(ValueError,match='Dados mínimos ausentes'):require_minimum(validate_policy(data))
