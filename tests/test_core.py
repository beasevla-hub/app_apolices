from datetime import date
from pathlib import Path
from openpyxl import Workbook,load_workbook
import pytest
from app.file_manager import sanitize_filename,publish
from app.models import PolicyData
from app.validator import validate_policy,require_minimum
from app.excel_apolices import update_workbook,ROBOT_MANAGED_COLUMNS
from app.excel_robot_control import RobotControl

def data(**kw):
    base=dict(empresa="THI Engenharia",tipo_empresa="THI",orgao="Órgão X",orgao_normalizado="ORGAO X",numero_concorrencia_original="01/2026",numero_concorrencia_normalizado="01-2026",vigencia_data_inicial=date(2026,1,2),vigencia_data_final=date(2027,1,1),confianca_geral=.95)
    base.update(kw);return PolicyData(**base)
def test_sanitize():assert sanitize_filename('a<b>:/\\c.pdf')=='a-b----c.pdf'
def test_validate_and_incomplete():
    x=validate_policy(data().model_dump(mode="json"));require_minimum(x)
    with pytest.raises(ValueError):require_minimum(PolicyData(confianca_geral=.5))
def test_robot_control_idempotency(tmp_path):
    ctl=RobotControl(tmp_path/'robot.xlsx');ctl.record(message_id='m1',uid='1',status='SUCESSO',hash_apolice='abc',hash_boleto='def')
    assert ctl.already_processed('m1',set()) and ctl.already_processed('other',{'abc'})
def test_excel_preserves_manual_and_null(tmp_path):
    path=tmp_path/'ops.xlsx';wb=Workbook();ws=wb.active;ws.append(ROBOT_MANAGED_COLUMNS+['STATUS','RESPONSÁVEL'])
    ws.append(['Órgão X','THI Engenharia','01/2026',None,None,None,None,None,None,None,'PAGO','BEA']);wb.save(path)
    update_workbook(path,data(processo_sei='SEI-1'),tmp_path/'backups')
    ws=load_workbook(path).active
    assert ws.cell(2,11).value=='PAGO' and ws.cell(2,12).value=='BEA'
    assert ws.cell(2,4).value=='SEI-1' and len(list((tmp_path/'backups').glob('*.xlsx')))==1
    update_workbook(path,data(processo_sei=None,objeto=None),tmp_path/'backups')
    ws=load_workbook(path).active;assert ws.cell(2,4).value=='SEI-1' and ws.cell(2,11).value=='PAGO'
def test_publish_transaction_and_paths(tmp_path):
    p=tmp_path/'p.pdf';b=tmp_path/'b.pdf';p.write_bytes(b'policy');b.write_bytes(b'bill')
    dest=publish(tmp_path/'root',data(),p,b)
    assert (dest/'01. APOLICE - ORGAO X - 01-2026.pdf').read_bytes()==b'policy'
    assert (dest/'08. BOLETO - ORGAO X - 01-2026.pdf').exists()

def test_robot_control_columns_are_aligned(tmp_path):
    path=tmp_path/'robot.xlsx';ctl=RobotControl(path)
    ctl.record(message_id='message',uid='42',status='SUCESSO',hash_apolice='a',hash_boleto='b',erro=None,pasta_destino='dest')
    row=ctl.rows()[0]
    assert row['status']=='SUCESSO' and row['data_processamento'] and row['erro'] is None and row['pasta_destino']=='dest'
