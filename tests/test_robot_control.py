from app.excel_robot_control import RobotControl

def test_attempt_state_retry_limit_and_error_clearing(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=2)
    process_id=ctl.begin(message_id='m',uid='1');assert ctl.find('m')['status']=='PROCESSANDO'
    ctl.record(message_id='m',uid='1',status='ERRO',erro='antigo',pasta_destino='antigo')
    ctl.begin(message_id='m',uid='1')
    assert ctl.find('m')['erro'] is None and ctl.find('m')['pasta_destino'] is None
    ctl.record(message_id='m',uid='1',status='ERRO',erro='atual')
    assert not ctl.can_retry('m','1')
    ctl.record(message_id='m',uid='1',status='SUCESSO',erro='stale')
    assert ctl.find('m')['status']=='SUCESSO' and ctl.find('m')['erro'] is None
    assert ctl.attempts('m','1')==2


def test_group_attempts_and_duplicate_hashes_are_scoped_by_lot(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=2)
    for lot,key in [('01','PAIR-a'),('02','PAIR-b')]:
        pid=ctl.begin(message_id='mail',uid='9',group_key=key,lote=lot,hash_apolice='same-policy',hash_boleto='same-bill')
        ctl.record(message_id='mail',uid='9',group_key=key,lote=lot,hash_apolice='same-policy',hash_boleto='same-bill',status='SUCESSO',id_processamento=pid)
    assert ctl.attempts('mail','9','PAIR-a')==1 and ctl.attempts('mail','9','PAIR-b')==1
    assert ctl.already_processed('',{'same-policy','same-bill'},lot='01')
    assert ctl.already_processed('',{'same-policy','same-bill'},lot='02')
    assert not ctl.already_processed('',{'same-policy','same-bill'},lot='03')
    assert ctl.all_attachments_processed(['same-policy','same-bill','same-policy','same-bill'])
    assert not ctl.all_attachments_processed(['same-policy','same-bill','extra'])
