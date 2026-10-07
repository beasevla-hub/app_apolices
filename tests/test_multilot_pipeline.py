import json
from email.message import EmailMessage
from pathlib import Path
from openpyxl import Workbook,load_workbook
from pypdf import PdfWriter
from app.email_client import MailMessage
from app.excel_apolices import ROBOT_MANAGED_COLUMNS
from app.excel_robot_control import RobotControl
from app.main import process_message,CountingOpenRouter
from tests.test_core import raw_result

def pdf_bytes():
    writer=PdfWriter();writer.add_blank_page(width=200,height=200)
    import io
    buffer=io.BytesIO();writer.write(buffer);return buffer.getvalue()
def make_message(tmp_path,filenames,message_id='multi@example'):
    em=EmailMessage();em['From']='arquivo@finlandiaseguros.com.br';em['To']='robot@example.com';em['Subject']='Apólices de lotes';em['Message-ID']=f'<{message_id}>';em.set_content('Documentos para diversos lotes')
    payload=pdf_bytes()
    for name in filenames:em.add_attachment(payload,maintype='application',subtype='pdf',filename=name)
    return MailMessage('445',f'<{message_id}>','arquivo@finlandiaseguros.com.br',em['Subject'],'2026-09-25',em.as_bytes())
def setup_excel(path):
    wb=Workbook();ws=wb.active;ws.title='APÓLICES';ws.append(ROBOT_MANAGED_COLUMNS);wb.save(path)
class GroupClient:
    def __init__(self,groups,fail_once=None,coherence=None):self.groups=groups;self.fail_once=fail_once;self.failed=False;self.coherence=coherence or {};self.classifications=0;self.analyses=[]
    def classify(self,files,names):self.classifications+=1;return {'grupos':self.groups,'outros':['extra.pdf'] if 'extra.pdf' in names else [],'observacoes':None}
    def analyze(self,policy,bill,expected_lot=None):
        self.analyses.append((policy.name,bill.name,expected_lot))
        if expected_lot==self.fail_once and not self.failed:self.failed=True;raise RuntimeError('falha simulada do lote')
        coherent=self.coherence.get(expected_lot,True)
        evidence={'valor':expected_lot,'fonte':'APOLICE','confianca':.98} if expected_lot else {'valor':None,'fonte':'NAO_IDENTIFICADO','confianca':.1}
        return raw_result(lote=evidence,par_coerente=coherent)
def g(lot,policy,bill):return {'lote':{'valor':lot,'fonte':'APOLICE','confianca':.98},'apolice':policy,'boleto':bill}
def run_process(tmp_path,message,client):
    excel=tmp_path/'ops.xlsx';setup_excel(excel);control=RobotControl(tmp_path/'robot.xlsx',max_attempts=4);counting=CountingOpenRouter(client)
    status=process_message(message,control,counting,root_dir=tmp_path/'docs',policies_excel=excel,backup_dir=tmp_path/'backups',temp_root=tmp_path/'temp',history_root=tmp_path/'history')
    return status,control,excel,counting

def test_two_lots_random_order_other_file_and_retry_only_failed_group(tmp_path):
    names=['policy_02.pdf','bill_01.pdf','extra.pdf','policy_01.pdf','bill_02.pdf']
    message=make_message(tmp_path,names,'retry@example')
    client=GroupClient([g('01','policy_01.pdf','bill_01.pdf'),g('02','policy_02.pdf','bill_02.pdf')],fail_once='02')
    status,control,excel,counting=run_process(tmp_path,message,client)
    assert status=='ERRO' and counting.classifications==1 and counting.analyses==2
    rows=control.rows();success=[r for r in rows if (r.get('group_key') or '').startswith('PAIR-') and r.get('status')=='SUCESSO']
    assert len(success)==1
    # Retry reuses exact classification and skips the already-successful pair.
    status=process_message(message,control,counting,root_dir=tmp_path/'docs',policies_excel=excel,backup_dir=tmp_path/'backups',temp_root=tmp_path/'temp',history_root=tmp_path/'history')
    assert status=='SUCESSO' and counting.classifications==1 and counting.analyses==3
    ws=load_workbook(excel)['APÓLICES'];lot_col=next(c for c in range(1,ws.max_column+1) if ws.cell(1,c).value=='LOTE')
    assert {ws.cell(r,lot_col).value for r in range(2,ws.max_row+1)}=={'01','02'}
    folders=[p.name for p in (tmp_path/'docs'/'THI').rglob('LOTE *') if p.is_dir()]
    assert set(folders)=={'LOTE 01','LOTE 02'} and len(list((tmp_path/'docs').rglob('*.pdf')))==4
    email_row=control.find(message.message_id,message.uid)
    metadata=json.loads((tmp_path/'history'/email_row['id_processamento']/'metadata.json').read_text())
    assert metadata['quantidade_pdfs']==5 and metadata['quantidade_grupos']==2
    assert all(entry['status']=='SUCESSO' for entry in metadata['lotes'])
    assert metadata['classificacao_cache_reutilizada'] is True
    assert metadata['chamadas_openrouter']=={'classificacao':0,'analises':1,'total':1}
    # Mesmo conteúdo em uma nova mensagem, quando todos os PDFs formam pares completos já concluídos,
    # é ignorado antes da classificação (sem custo adicional).
    copied=make_message(tmp_path,['policy_01.pdf','bill_01.pdf','policy_02.pdf','bill_02.pdf'],'copy@example')
    calls=(counting.classifications,counting.analyses)
    assert process_message(copied,control,counting,root_dir=tmp_path/'docs',policies_excel=excel,backup_dir=tmp_path/'backups',temp_root=tmp_path/'temp',history_root=tmp_path/'history')=='IGNORADO'
    assert (counting.classifications,counting.analyses)==calls
    assert process_message(message,control,counting,root_dir=tmp_path/'docs',policies_excel=excel,backup_dir=tmp_path/'backups',temp_root=tmp_path/'temp',history_root=tmp_path/'history')=='IGNORADO'
    assert (counting.classifications,counting.analyses)==calls

def test_ten_groups_make_ten_separate_analyses(tmp_path):
    names=[f'{kind}_{idx:02d}.pdf' for idx in range(1,11) for kind in ('apolice','boleto')]
    names=names[::2]+names[1::2][::-1]
    message=make_message(tmp_path,names,'ten@example')
    groups=[g(f'{idx:02d}',f'apolice_{idx:02d}.pdf',f'boleto_{idx:02d}.pdf') for idx in range(1,11)]
    status,control,excel,counting=run_process(tmp_path,message,GroupClient(groups))
    assert status=='SUCESSO' and counting.classifications==1 and counting.analyses==10
    assert load_workbook(excel)['APÓLICES'].max_row==11
    assert len(list((tmp_path/'docs').rglob('*.pdf')))==20

def test_cross_lot_pair_rejected_by_independent_analysis(tmp_path):
    names=['policy_01.pdf','bill_01.pdf','policy_02.pdf','bill_02.pdf']
    message=make_message(tmp_path,names,'mismatch@example')
    groups=[g('01','policy_01.pdf','bill_02.pdf'),g('02','policy_02.pdf','bill_01.pdf')]
    client=GroupClient(groups,coherence={'01':False,'02':False})
    status,control,excel,counting=run_process(tmp_path,message,client)
    assert status=='ERRO' and counting.analyses==2
    assert not (tmp_path/'docs').exists() and load_workbook(excel)['APÓLICES'].max_row==1
    group_rows=[r for r in control.rows() if (r.get('group_key') or '').startswith('PAIR-')]
    assert len(group_rows)==2 and all(r['status']=='ERRO' for r in group_rows)


def test_other_only_message_is_ignored_without_policy_analysis(tmp_path):
    message=make_message(tmp_path,['extra-a.pdf','extra-b.pdf'],'other@example')
    class OtherClient:
        def __init__(self):self.classifications=0;self.analyses=0
        def classify(self,files,names):self.classifications+=1;return {'grupos':[],'outros':names,'observacoes':None}
        def analyze(self,*args,**kwargs):self.analyses+=1;raise AssertionError('não deve analisar OUTRO')
    status,control,excel,counting=run_process(tmp_path,message,OtherClient())
    assert status=='IGNORADO' and counting.classifications==1 and counting.analyses==0
    assert control.find(message.message_id,message.uid)['status']=='IGNORADO'
    assert not (tmp_path/'docs').exists() and load_workbook(excel)['APÓLICES'].max_row==1


def test_associated_lot_is_operational_when_policy_has_no_documentary_lot(tmp_path):
    message=make_message(tmp_path,['policy.pdf','bill.pdf'],'associated-only@example')
    class AssociatedOnlyClient:
        def classify(self,files,names):return {'grupos':[g('1','policy.pdf','bill.pdf')],'outros':[],'observacoes':None}
        def analyze(self,policy,bill,expected_lot=None):
            return raw_result(lote={'valor':None,'fonte':'NAO_IDENTIFICADO','confianca':.1})
    status,control,excel,counting=run_process(tmp_path,message,AssociatedOnlyClient())
    assert status=='SUCESSO' and counting.classifications==1 and counting.analyses==1
    ws=load_workbook(excel)['APÓLICES'];lot_col=next(c for c in range(1,ws.max_column+1) if ws.cell(1,c).value=='LOTE')
    assert ws.cell(2,lot_col).value=='1'
    group_row=next(row for row in control.rows() if (row.get('group_key') or '').startswith('PAIR-'))
    assert group_row['lote']=='1' and group_row['status']=='SUCESSO'
    email=control.find(message.message_id,message.uid)
    metadata=json.loads((tmp_path/'history'/email['id_processamento']/'metadata.json').read_text())
    item=metadata['lotes'][0]
    assert item['lote']=='1' and item['lote_associado']=='1' and item['lote_documental'] is None
    assert len(list((tmp_path/'docs').rglob('LOTE *')))==0


def test_documentary_lot_conflict_with_associated_group_is_rejected(tmp_path):
    message=make_message(tmp_path,['policy.pdf','bill.pdf'],'lot-conflict@example')
    class ConflictingLotClient:
        def classify(self,files,names):return {'grupos':[g('1','policy.pdf','bill.pdf')],'outros':[],'observacoes':None}
        def analyze(self,policy,bill,expected_lot=None):
            return raw_result(lote={'valor':'2','fonte':'APOLICE','confianca':.99})
    status,control,excel,counting=run_process(tmp_path,message,ConflictingLotClient())
    assert status=='ERRO' and counting.analyses==1
    row=next(row for row in control.rows() if (row.get('group_key') or '').startswith('PAIR-'))
    assert row['status']=='ERRO' and 'não confirma associação' in row['erro']
    assert not (tmp_path/'docs').exists() and load_workbook(excel)['APÓLICES'].max_row==1


def test_retry_errors_reuses_classification_and_reanalyzes_only_failed_group(tmp_path):
    names=[f'{kind}_{idx:02d}.pdf' for idx in range(1,4) for kind in ('policy','bill')]
    message=make_message(tmp_path,names,'retry-errors-groups@example')
    groups=[g('01','policy_01.pdf','bill_01.pdf'),g('02','policy_02.pdf','bill_02.pdf'),g('03','policy_03.pdf','bill_03.pdf')]
    client=GroupClient(groups,fail_once='02')
    excel=tmp_path/'ops.xlsx';setup_excel(excel);control=RobotControl(tmp_path/'robot.xlsx',max_attempts=1);counting=CountingOpenRouter(client)
    kwargs=dict(root_dir=tmp_path/'docs',policies_excel=excel,backup_dir=tmp_path/'backups',temp_root=tmp_path/'temp',history_root=tmp_path/'history',mode='BACKFILL')
    assert process_message(message,control,counting,**kwargs)=='ERRO'
    assert counting.classifications==1 and counting.analyses==3
    rows=[row for row in control.rows() if (row.get('group_key') or '').startswith('PAIR-')]
    assert sorted(row['status'] for row in rows)==['ERRO','SUCESSO','SUCESSO']
    attempts_before={row['group_key']:row['tentativas'] for row in rows}
    assert max(attempts_before.values())==1
    assert process_message(message,control,counting,retry_errors=True,**kwargs)=='SUCESSO'
    # A classificação vem do cache e apenas o grupo 02 recebe uma nova análise.
    assert counting.classifications==1 and counting.analyses==4
    rows=[row for row in control.rows() if (row.get('group_key') or '').startswith('PAIR-')]
    assert all(row['status']=='SUCESSO' for row in rows)
    assert sorted(row['tentativas'] for row in rows)==[1,1,2]
