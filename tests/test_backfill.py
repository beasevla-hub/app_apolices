from datetime import date
from email.message import EmailMessage
import pytest
from app.email_client import EmailClient
from app.main import parse_backfill_date

class FakeIMAP:
    def __init__(self,count=120,wrong_sender_at=None):
        self.calls=[];self.messages={};self.ids=[]
        for index in range(1,count+1):
            msg=EmailMessage();msg['From']=('bad@example.org' if index==wrong_sender_at else 'Arquivo <arquivo@finlandiaseguros.com.br>')
            msg['Subject']=f'Apólice {index}';msg['Date']='Wed, 12 Aug 2026 10:00:00 -0300';msg['Message-ID']=f'<{index}@example>'
            msg.set_content('mensagem antiga já lida')
            uid=str(index).encode();self.ids.append(uid);self.messages[uid]=msg.as_bytes()
    def uid(self,command,*args):
        self.calls.append((command,args))
        if command=='search':return 'OK',[b' '.join(self.ids)]
        if command=='fetch':return 'OK',[(b'RFC822',self.messages[args[0]])]
        raise AssertionError(command)

def test_parse_dates_and_inverted_period():
    assert parse_backfill_date('01/08/2026')==date(2026,8,1)
    assert parse_backfill_date('30/09/2026')==date(2026,9,30)
    with pytest.raises(Exception):parse_backfill_date('31/02/2026')

def test_messages_between_uses_inclusive_end_and_sender_filter_without_limit():
    imap=FakeIMAP(count=125,wrong_sender_at=4)
    client=EmailClient('host',993,'user','pass','INBOX',('@finlandiaseguros.com.br',));client.conn=imap
    messages=list(client.messages_between(date(2026,8,1),date(2026,9,30)))
    search=[entry for entry in imap.calls if entry[0]=='search'][0][1]
    assert search== (None,'SINCE 01-Aug-2026','BEFORE 01-Oct-2026')
    assert len(messages)==124 and client.last_found_count==125 and client.last_relevant_count==124
    assert messages[0].uid=='1' and messages[-1].uid=='125'

def test_invalid_reversed_period_does_not_query_server():
    imap=FakeIMAP(1);client=EmailClient('host',993,'user','pass','INBOX',());client.conn=imap
    with pytest.raises(ValueError):list(client.messages_between(date(2026,9,1),date(2026,8,1)))
    assert imap.calls==[]


def test_backfill_dry_run_keeps_history_but_does_not_publish(tmp_path):
    from pypdf import PdfWriter
    from tests.test_core import raw_result
    from app.email_client import MailMessage
    from app.excel_robot_control import RobotControl
    from app.main import process_message
    source=tmp_path/'source';source.mkdir()
    pdfs=[]
    for name in ('apolice.pdf','boleto.pdf'):
        path=source/name;writer=PdfWriter();writer.add_blank_page(width=200,height=200)
        with path.open('wb') as f:writer.write(f)
        pdfs.append(path)
    message=EmailMessage();message['From']='arquivo@finlandiaseguros.com.br';message['Subject']='Histórico';message['Message-ID']='<backfill-dry>'
    message.set_content('anexos');
    for path in pdfs:message.add_attachment(path.read_bytes(),maintype='application',subtype='pdf',filename=path.name)
    mail=MailMessage('77','<backfill-dry>','arquivo@finlandiaseguros.com.br','Histórico','2026-08-15',message.as_bytes())
    class FakeOpenRouter:
        def classify(self,files,names):return {'grupos':[{'lote':{'valor':None,'fonte':'NAO_IDENTIFICADO','confianca':.1},'apolice':'apolice.pdf','boleto':'boleto.pdf'}],'outros':[],'observacoes':None}
        def analyze(self,policy,bill):return raw_result()
    control=RobotControl(tmp_path/'robot.xlsx')
    result=process_message(mail,control,client=FakeOpenRouter(),dry_run=True,mode='BACKFILL',root_dir=tmp_path/'definitive',policies_excel=tmp_path/'ops.xlsx',backup_dir=tmp_path/'backups',temp_root=tmp_path/'temp',history_root=tmp_path/'history')
    record=control.find('<backfill-dry>')
    metadata=__import__('json').loads((tmp_path/'history'/record['id_processamento']/'metadata.json').read_text())
    assert result=='DRY_RUN' and record['status']=='IGNORADO' and 'DRY_RUN' in record['erro']
    assert metadata['modo_execucao']=='BACKFILL_DRY_RUN'
    assert not (tmp_path/'definitive').exists() and not (tmp_path/'ops.xlsx').exists()


def test_cli_rejects_invalid_or_reversed_dates_before_io(monkeypatch):
    import sys
    from app.main import main
    for args in [
        ['app.main','--backfill','--inicio','31/02/2026','--fim','30/09/2026'],
        ['app.main','--backfill','--inicio','30/09/2026','--fim','01/08/2026'],
        ['app.main','--backfill','--inicio','01/08/2026'],
    ]:
        monkeypatch.setattr(sys,'argv',args)
        with pytest.raises(SystemExit) as error:main()
        assert error.value.code==2


def test_imap_fetch_reconnects_and_retries_same_uid(monkeypatch):
    import app.email_client as email_client
    from app.email_client import IMAPConnectionLost
    msg=EmailMessage();msg['From']='arquivo@finlandiaseguros.com.br';msg['Subject']='UID retry';msg['Date']='Wed, 12 Aug 2026 10:00:00 -0300';msg['Message-ID']='<77@example>';msg.set_content('body');raw=msg.as_bytes()
    class Flaky:
        def __init__(self):self.fetches=[]
        def uid(self,command,*args):
            if command=='fetch':self.fetches.append(args[0]);raise ConnectionResetError('socket reset')
            raise AssertionError(command)
        def logout(self):pass
    class Recovered:
        def __init__(self):self.fetches=[]
        def uid(self,command,*args):
            if command=='fetch':self.fetches.append(args[0]);return 'OK',[(b'RFC822',raw)]
            raise AssertionError(command)
        def logout(self):pass
    first=Flaky();recovered=Recovered();client=EmailClient('host',993,'u','p','INBOX',('@finlandiaseguros.com.br',),reconnect_delays=(0,));client.conn=first
    monkeypatch.setattr(email_client.time,'sleep',lambda _:None)
    monkeypatch.setattr(client,'_connect_once',lambda:setattr(client,'conn',recovered))
    messages=list(client._messages_from_uids([b'77']))
    assert [message.uid for message in messages]==['77'] and first.fetches==[b'77'] and recovered.fetches==[b'77']

def test_imap_reconnect_failure_is_bounded_and_transport_not_document_error(monkeypatch):
    import app.email_client as email_client
    from app.email_client import IMAPConnectionLost
    class Flaky:
        def uid(self,*args):raise BrokenPipeError('pipe closed')
        def logout(self):pass
    attempts={'count':0}
    def failed_connect():attempts['count']+=1;raise ConnectionError('remote unavailable')
    client=EmailClient('host',993,'u','p','INBOX',(),reconnect_delays=(0,0));client.conn=Flaky()
    monkeypatch.setattr(email_client.time,'sleep',lambda _:None);monkeypatch.setattr(client,'_connect_once',failed_connect)
    with pytest.raises(IMAPConnectionLost,match='lote parcialmente processado'):
        list(client._messages_from_uids([b'9']))
    assert attempts['count']==2
