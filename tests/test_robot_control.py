from app.excel_robot_control import RobotControl,HEADERS


def test_attempt_history_is_audit_only_and_success_clears_error(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=2)
    first=ctl.begin(message_id='m',uid='1')
    assert first and ctl.find('m')['status']=='PROCESSANDO' and ctl.attempts('m','1')==1
    ctl.record(message_id='m',uid='1',status='ERRO',erro='antigo',pasta_destino='antigo')
    second=ctl.begin(message_id='m',uid='1')
    assert second!=first and ctl.find('m')['erro'] is None and ctl.find('m')['pasta_destino'] is None
    ctl.record(message_id='m',uid='1',status='ERRO',erro='atual')
    third=ctl.begin(message_id='m',uid='1')
    assert third not in {first,second} and ctl.attempts('m','1')==3
    ctl.record(message_id='m',uid='1',status='SUCESSO',erro='stale')
    assert ctl.find('m')['status']=='SUCESSO' and ctl.find('m')['erro'] is None
    assert len(ctl.rows()[0])>=len(HEADERS)


def test_completed_pair_requires_success_and_both_exact_hashes(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=1)
    ctl.record(message_id='m1',uid='1',group_key='PAIR-a',lote='01',status='SUCESSO',tentativas=100,hash_apolice='policy',hash_boleto='bill',pasta_destino=r'C:\docs\01. APOLICE - ORGAO - 01-2026.pdf')
    row=ctl.completed_pair('m1','PAIR-a','policy','bill',lot='01')
    assert row and row['status']=='SUCESSO' and '01. APOLICE - ORGAO' in row['pasta_destino']
    assert ctl.completed_pair('m1','PAIR-a','changed','bill',lot='01') is None
    assert ctl.completed_pair('m1','PAIR-a','policy','different',lot='01') is None
    assert ctl.completed_pair('m1','PAIR-a','bill','policy',lot='01') is None
    assert ctl.completed_pair('m1','PAIR-a','policy','bill',lot='02') is None
    assert ctl.completed_pair('another-email','PAIR-z','policy','bill',lot='01') is not None


def test_nonfinal_states_and_high_attempt_counts_do_not_create_success(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=1)
    for status in ('ERRO','PROCESSANDO','IGNORADO','ESTADO_ANTIGO'):
        ctl.record(message_id=status,group_key='PAIR',status=status,tentativas=100,hash_apolice='p',hash_boleto='b')
        assert ctl.completed_pair(status,'PAIR','p','b') is None


def test_group_attempts_and_duplicate_hashes_are_scoped_by_lot(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=1)
    for lot,key in [('01','PAIR-a'),('02','PAIR-b')]:
        pid=ctl.begin(message_id='mail',uid='9',group_key=key,lote=lot,hash_apolice='same-policy',hash_boleto='same-bill')
        ctl.record(message_id='mail',uid='9',group_key=key,lote=lot,hash_apolice='same-policy',hash_boleto='same-bill',status='SUCESSO',id_processamento=pid)
    assert ctl.attempts('mail','9','PAIR-a')==1 and ctl.attempts('mail','9','PAIR-b')==1
    assert ctl.completed_pair('mail','PAIR-a','same-policy','same-bill',lot='01')
    assert ctl.completed_pair('mail','PAIR-b','same-policy','same-bill',lot='02')
    assert ctl.completed_pair('mail','PAIR-c','same-policy','same-bill',lot='03') is None

def test_multilot_pair_success_requires_exact_hashes_and_exact_lot_set(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx')
    ctl.record(message_id='mail',uid='9',group_key='PAIR-multi',status='SUCESSO',hash_apolice='policy-hash',hash_boleto='bill-hash',lotes='["01","02","03","04"]')
    assert ctl.completed_pair('mail','PAIR-multi','policy-hash','bill-hash',lotes=['01','02','03','04'])
    assert ctl.completed_pair('mail','PAIR-other','policy-hash','bill-hash',lotes=['01','02','03','04'])
    assert ctl.completed_pair('mail','PAIR-multi','changed','bill-hash',lotes=['01','02','03','04']) is None
    assert ctl.completed_pair('mail','PAIR-multi','policy-hash','bill-hash',lotes=['01','02']) is None
    # Um registro legado escalar não serve como sucesso multilote compatível.
    ctl.record(message_id='legacy',group_key='PAIR-old',status='SUCESSO',hash_apolice='p',hash_boleto='b',lote='1 e 2')
    assert ctl.completed_pair('legacy','PAIR-new','p','b',lotes=['01','02']) is None
