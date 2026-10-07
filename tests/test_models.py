from datetime import date
import pytest
from app.models import PolicyData,Evidence

def test_model_validates_company_evidence_and_date():
    item=PolicyData(empresa_normalizada='PHAS',tipo_empresa='PHAS',vigencia_data_inicial='2026-08-01',vigencia_data_final='2027-08-01',confianca_geral=.9,evidencias={'empresa_normalizada':Evidence(valor='PHAS',fonte='APOLICE',confianca=.99)})
    assert item.vigencia_data_inicial==date(2026,8,1)

def test_model_rejects_conflicting_company_and_dates():
    with pytest.raises(ValueError):PolicyData(empresa_normalizada='THI',tipo_empresa='PHAS',confianca_geral=.9)
    with pytest.raises(ValueError):PolicyData(vigencia_data_inicial='2027-01-01',vigencia_data_final='2026-12-31',confianca_geral=.9)
