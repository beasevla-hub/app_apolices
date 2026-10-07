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
