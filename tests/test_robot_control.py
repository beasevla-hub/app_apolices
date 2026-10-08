from app.excel_robot_control import RobotControl
from datetime import datetime,timedelta,timezone

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


def test_force_retry_error_overrides_only_error_status_and_keeps_attempt_history(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=5)
    for mid,status,attempts in [('success','SUCESSO',5),('error5','ERRO',5),('error20','ERRO',20),('ignored','IGNORADO',5)]:
        ctl.record(message_id=mid,status=status,tentativas=attempts)
    assert not ctl.can_retry('success',force_retry_error=True)
    assert not ctl.can_retry('error5')
    assert ctl.can_retry('error5',force_retry_error=True)
    assert ctl.can_retry('error20',force_retry_error=True)
    assert not ctl.can_retry('ignored',force_retry_error=True)
    assert ctl.attempts('error5')==5
    ctl.begin(message_id='error5')
    assert ctl.attempts('error5')==6


def test_force_retry_does_not_change_normal_retry_limit(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=5)
    ctl.record(message_id='error',status='ERRO',tentativas=5)
    ctl.record(message_id='ignored',status='IGNORADO',tentativas=2)
    assert not ctl.can_retry('error')
    assert ctl.can_retry('ignored')
    assert not ctl.can_retry('ignored',force_retry_error=True)


def test_force_retry_processing_only_when_iso_timestamp_is_stale(tmp_path,caplog):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=5)
    now=datetime.now(timezone.utc)
    ctl.record(message_id='fresh',status='PROCESSANDO',tentativas=5,data_ultima_tentativa=(now-timedelta(minutes=5)).isoformat(timespec='seconds'))
    ctl.record(message_id='stale',status='PROCESSANDO',tentativas=5,data_ultima_tentativa=(now-timedelta(hours=2)).isoformat(timespec='seconds'))
    ctl.record(message_id='invalid',status='PROCESSANDO',tentativas=20,data_ultima_tentativa='not-a-date')
    ctl.record(message_id='missing',status='PROCESSANDO',tentativas=20,data_ultima_tentativa=None)
    assert not ctl.can_retry('fresh',force_retry_error=True,stale_processing_minutes=30)
    assert ctl.can_retry('stale',force_retry_error=True,stale_processing_minutes=30)
    assert not ctl.can_retry('invalid',force_retry_error=True,stale_processing_minutes=30)
    assert not ctl.can_retry('missing',force_retry_error=True,stale_processing_minutes=30)
    assert 'data_ultima_tentativa' in caplog.text


def test_processing_timestamp_naive_local_iso_and_future_are_safe(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx',max_attempts=1)
    ctl.record(message_id='stale-local',status='PROCESSANDO',tentativas=10,data_ultima_tentativa=(datetime.now()-timedelta(hours=1)).isoformat(timespec='seconds'))
    ctl.record(message_id='future',status='PROCESSANDO',tentativas=10,data_ultima_tentativa=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(timespec='seconds'))
    assert ctl.can_retry('stale-local',force_retry_error=True,stale_processing_minutes=30)
    assert not ctl.can_retry('future',force_retry_error=True,stale_processing_minutes=30)
