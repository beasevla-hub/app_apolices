from datetime import date
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.table import Table
import pytest
from app.models import PolicyData
from app.excel_apolices import update_workbook,ROBOT_MANAGED_COLUMNS

def item(process='SEI-1'):
    return PolicyData(empresa='THI Engenharia',empresa_normalizada='THI',orgao='Sub Parelheiros',orgao_normalizado='SUB PARELHEIROS',numero_concorrencia_original='018/SEME/2026',numero_concorrencia_normalizado='018-SEME-2026',processo_sei=process,vigencia_data_inicial=date(2026,8,1),vigencia_data_final=date(2027,8,1),confianca_geral=.9)
def workbook(path,rows):
    wb=Workbook();ws=wb.active;ws.title='APÓLICES';ws.append(ROBOT_MANAGED_COLUMNS+['STATUS','RESPONSÁVEL'])
    for row in rows:ws.append(row)
    wb.save(path)
def row(process):return ['Sub Parelheiros','THI Engenharia','018/SEME/2026',process,'manual objeto',None,None,None,None,None,'PAGO','Bea']
def test_different_sei_does_not_fallback_to_org(tmp_path):
    path=tmp_path/'ops.xlsx';workbook(path,[row('SEI-1')])
    assert update_workbook(path,item('SEI-2'),tmp_path/'backups')=='ADICIONADO'
    ws=load_workbook(path)['APÓLICES'];assert ws.max_row==3 and ws['D2'].value=='SEI-1' and ws['D3'].value=='SEI-2'
def test_same_sei_updates_preserves_manual_and_null(tmp_path):
    path=tmp_path/'ops.xlsx';workbook(path,[row('SEI-1')])
    update_workbook(path,item('SEI-1'),tmp_path/'backups');ws=load_workbook(path)['APÓLICES']
    assert ws.max_row==2 and ws['K2'].value=='PAGO' and ws['L2'].value=='Bea' and ws['E2'].value=='manual objeto'
def test_missing_operational_sheet_fails_without_changing_other_sheet(tmp_path):
    path=tmp_path/'ops.xlsx';wb=Workbook();wb.active.title='Outra';wb.save(path)
    with pytest.raises(ValueError,match='APÓLICES'):update_workbook(path,item(),tmp_path/'backups')
    assert load_workbook(path).sheetnames==['Outra']
def test_missing_sei_uses_org_fallback_and_multiple_matches_fail(tmp_path):
    path=tmp_path/'ops.xlsx';workbook(path,[row(None)])
    update_workbook(path,item(None),tmp_path/'backups');assert load_workbook(path)['APÓLICES'].max_row==2
    path2=tmp_path/'dup.xlsx';workbook(path2,[row(None),row(None)])
    with pytest.raises(ValueError,match='POSSIVEL_DUPLICATA'):update_workbook(path2,item(None),tmp_path/'backups')

def test_existing_table_filter_formula_and_manual_column_are_untouched(tmp_path):
    path=tmp_path/'table.xlsx';workbook(path,[row('SEI-1')]);wb=load_workbook(path);ws=wb['APÓLICES']
    table=Table(displayName='TeamTable',ref='A1:L2');ws.add_table(table);ws.auto_filter.ref='A1:L2'
    ws['M1']='MANUAL FORMULA';ws['M2']='=1+1';wb.save(path)
    update_workbook(path,item('SEI-1'),tmp_path/'backups')
    ws=load_workbook(path,data_only=False)['APÓLICES']
    assert ws.tables['TeamTable'].ref=='A1:L2' and ws.auto_filter.ref=='A1:L2' and ws['M2'].value=='=1+1'
