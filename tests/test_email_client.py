from email.message import EmailMessage

from app.email_client import EmailClient


def _message_bytes():
    message=EmailMessage()
    message['From']='Arquivo <arquivo@finlandiaseguros.com.br>'
    message['To']='robot@example.com'
    message['Subject']='Apólice'
    message['Message-ID']='<imap-date@example>'
    message['Date']='Fri, 09 Oct 2026 05:00:00 -0300'
    message.set_content('Anexo será recebido em FETCH')
    return message.as_bytes()


def test_imap_fetch_captures_server_internaldate_separately_from_message_date():
    raw=_message_bytes()
    client=EmailClient('imap.test',993,'user','password','INBOX',('@finlandiaseguros.com.br',))
    calls=[]
    metadata=b'1 (UID 44 INTERNALDATE "09-Oct-2026 11:31:42 +0000")'
    def fake_uid(*args):
        calls.append(args)
        return 'OK',[(metadata,None),(b'1 (UID 44 BODY[] {100})',raw)]
    client._uid=fake_uid
    result=list(client._messages_from_uids([b'44']))
    assert calls[0][0:2]==('fetch',b'44')
    assert calls[0][2]==b'(BODY.PEEK[] INTERNALDATE)'
    assert len(result)==1
    assert result[0].date=='2026-10-09T05:00:00-03:00'
    assert result[0].received_at=='2026-10-09T11:31:42+00:00'


def test_imap_internaldate_missing_keeps_legacy_date_fallback_available():
    raw=_message_bytes()
    client=EmailClient('imap.test',993,'user','password','INBOX',('@finlandiaseguros.com.br',))
    client._uid=lambda *args:('OK',[(b'1 (UID 44 BODY[] {100})',raw)])
    result=list(client._messages_from_uids([b'44']))
    assert result[0].received_at is None
    assert result[0].date=='2026-10-09T05:00:00-03:00'
