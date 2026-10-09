import pytest
from app.validator import validate_policy,require_minimum

def result(confidence=.9):
    company='THI ENGENHARIA E ARQUITETURA LTDA.'
    fields={'empresa':company,'empresa_normalizada':company,'cnpj':None,'orgao':'Órgão','numero_concorrencia_normalizado':'10-2026','vigencia_data_inicial':'2026-08-01','vigencia_data_final':'2027-08-01'}
    data={key:{'valor':value,'fonte':'APOLICE','confianca':confidence} for key,value in fields.items()}
    data['cnpj']={'valor':None,'fonte':'NAO_IDENTIFICADO','confianca':.1};data['confianca_geral']=.99;data['lote']={'valor':None,'fonte':'NAO_IDENTIFICADO','confianca':.1};data['par_coerente']=True;return data

def test_validator_accepts_high_confidence_with_evidence():require_minimum(validate_policy(result()))
def test_validator_rejects_low_confidence_and_missing_evidence():
    with pytest.raises(ValueError,match='Confiança insuficiente'):require_minimum(validate_policy(result(.3)))
    data=result();del data['orgao']
    with pytest.raises(ValueError,match='Dados mínimos ausentes'):require_minimum(validate_policy(data))

def test_validator_rejects_incoherent_pair_and_unsupported_lot():
    data=result();data['par_coerente']=False
    with pytest.raises(ValueError,match='coerência confirmada'):require_minimum(validate_policy(data))
    data=result();data['lote']={'valor':'01','fonte':'APOLICE','confianca':.4}
    with pytest.raises(ValueError,match='Confiança insuficiente para o lote'):require_minimum(validate_policy(data))

def test_group_association_can_supply_operational_lot_without_documentary_claim():
    data=result();data['lote']={'valor':None,'fonte':'NAO_IDENTIFICADO','confianca':.1}
    parsed=validate_policy(data,lote_associado='1');require_minimum(parsed,lote_associado='1')
    assert parsed.lote_documental is None and parsed.lote_associado=='1' and parsed.lote_operacional=='1'
    echoed=result();echoed['lote']={'valor':'1','fonte':'NAO_IDENTIFICADO','confianca':.1}
    parsed=validate_policy(echoed,lote_associado='1');require_minimum(parsed,lote_associado='1')
    assert parsed.lote_documental is None and 'lote' not in parsed.evidencias and parsed.lote_operacional=='1'

def test_documentary_lot_equal_to_group_is_retained_but_conflict_is_rejected_by_pipeline():
    data=result();data['lote']={'valor':'1','fonte':'APOLICE','confianca':.98}
    parsed=validate_policy(data,lote_associado='1');require_minimum(parsed,lote_associado='1')
    assert parsed.lote_documental=='1' and parsed.lote_operacional=='1'
    conflict=validate_policy({**data,'lote':{'valor':'2','fonte':'APOLICE','confianca':.98}},lote_associado='1')
    assert conflict.lote_documental=='2' and conflict.lote_operacional=='1'

def test_structured_lots_keep_individual_premiums_and_clear_compound_scalar():
    evidence=lambda value:{'valor':value,'fonte':'APOLICE','confianca':.97}
    data=result();data['lote']=evidence('1 e 2');data['lotes']=[{'numero':evidence('1'),'valor_premio':evidence(1100.5)},{'numero':evidence('2'),'valor_premio':evidence(900.25)}]
    parsed=validate_policy(data,lotes_associados=['1','2']);require_minimum(parsed)
    assert parsed.lote is None and 'lote' not in parsed.evidencias
    assert [str(item.numero.valor) for item in parsed.lotes]==['1','2']
    assert [item.valor_premio.valor for item in parsed.lotes]==[1100.5,900.25]
    assert parsed.lotes_associados==['1','2'] and parsed.lote_operacional is None

def test_structured_lot_requires_evidence_and_rejects_duplicate_identifiers():
    evidence=lambda value,confidence=.97:{'valor':value,'fonte':'APOLICE','confianca':confidence}
    bad=result();bad['lotes']=[{'numero':evidence('1',.4),'valor_premio':evidence(None)}]
    with pytest.raises(ValueError,match='Confiança/fonte insuficiente no número'):
        require_minimum(validate_policy(bad))
    duplicate=result();duplicate['lotes']=[{'numero':evidence('1'),'valor_premio':evidence(None)},{'numero':evidence('1'),'valor_premio':evidence(None)}]
    with pytest.raises(ValueError,match='duplicado'):
        require_minimum(validate_policy(duplicate))

def test_company_normalization_accepts_legal_variants_and_preserves_original():
    data=result();data['empresa']={'valor':'SUBPREFEITURA SÃO MATEUS','fonte':'APOLICE','confianca':.98}
    data['empresa_normalizada']={'valor':'thi engenharia e arquitetura ltda.','fonte':'APOLICE','confianca':.98}
    parsed=validate_policy(data)
    assert parsed.empresa=='SUBPREFEITURA SÃO MATEUS' and parsed.empresa_normalizada=='THI' and parsed.tipo_empresa=='THI'

def test_configured_cnpj_takes_precedence_over_conflicting_company_name():
    data=result();data['empresa']={'valor':'PHAS ENGENHARIA, CONSTRUÇÕES E SERVIÇOS LTDA-ME','fonte':'APOLICE','confianca':.98}
    data['empresa_normalizada']={'valor':'PHAS ENGENHARIA CONSTRUCOES E SERVICOS LTDA ME','fonte':'APOLICE','confianca':.98}
    data['tipo_empresa']='PHAS';data['cnpj']={'valor':'09.195.930/0001-12','fonte':'APOLICE','confianca':.99}
    names={'THI':'THI ENGENHARIA E ARQUITETURA LTDA','PHAS':'PHAS ENGENHARIA, CONSTRUÇÕES E SERVIÇOS LTDA-ME'}
    cnpjs={'THI':'09.195.930/0001-12','PHAS':'11.111.111/0001-11'}
    parsed=validate_policy(data,configured_names=names,configured_cnpjs=cnpjs)
    assert parsed.empresa.startswith('PHAS') and parsed.empresa_normalizada=='THI' and parsed.tipo_empresa=='THI'

def test_thi_legal_name_and_configured_cnpj_normalize_to_thi():
    data=result();legal='THI ENGENHARIA E ARQUITETURA LTDA.'
    data['empresa']={'valor':legal,'fonte':'APOLICE','confianca':.99}
    data['empresa_normalizada']={'valor':legal,'fonte':'APOLICE','confianca':.99}
    data['cnpj']={'valor':'09.195.930/0001-12','fonte':'APOLICE','confianca':.99}
    names={'THI':'THI ENGENHARIA E ARQUITETURA LTDA','PHAS':'PHAS ENGENHARIA, CONSTRUÇÕES E SERVIÇOS LTDA-ME'}
    parsed=validate_policy(data,configured_names=names,configured_cnpjs={'THI':'09195930000112','PHAS':''})
    assert parsed.empresa==legal and parsed.empresa_normalizada=='THI' and parsed.tipo_empresa=='THI'

def test_unknown_company_remains_null_and_requires_review():
    data=result();unknown='EMPRESA COMPLETAMENTE DESCONHECIDA S A'
    data['empresa']={'valor':unknown,'fonte':'APOLICE','confianca':.99}
    data['empresa_normalizada']={'valor':unknown,'fonte':'APOLICE','confianca':.99}
    parsed=validate_policy(data)
    assert parsed.empresa_normalizada is None and parsed.tipo_empresa is None
    with pytest.raises(ValueError,match='Dados mínimos ausentes'):require_minimum(parsed)
