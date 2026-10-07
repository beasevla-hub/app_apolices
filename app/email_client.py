"""Acesso IMAP SSL e consulta de mensagens por intervalo inclusivo."""
import email,imaplib,time
from dataclasses import dataclass
from datetime import date,timedelta
from email.header import decode_header,make_header
from email.utils import parsedate_to_datetime,parseaddr
from pathlib import Path
from .logger import get_logger
log=get_logger()
_MONTHS=("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")
def _imap_date(value:date)->str:return f"{value.day:02d}-{_MONTHS[value.month-1]}-{value.year:04d}"

@dataclass
class MailMessage:
    uid:str;message_id:str;sender:str;subject:str;date:str;raw:bytes

class EmailClient:
    def __init__(self,host:str,port:int,user:str,password:str,folder:str,domains:tuple[str,...],use_ssl:bool=True):
        self.host,self.port,self.user,self.password,self.folder,self.domains,self.use_ssl=host,port,user,password,folder,domains,use_ssl
        self.conn=None;self.last_found_count=0;self.last_relevant_count=0
    def __enter__(self):
        error=None
        for attempt in range(3):
            try:
                cls=imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4
                self.conn=cls(self.host,self.port,timeout=45);self.conn.login(self.user,self.password)
                status,_=self.conn.select(self.folder,readonly=True)
                if status!="OK":raise RuntimeError(f"Não foi possível selecionar pasta {self.folder}")
                return self
            except Exception as exc:
                error=exc
                if self.conn:
                    try:self.conn.logout()
                    except Exception:pass
                if attempt<2:time.sleep(2**attempt)
        raise RuntimeError(f"Falha ao conectar IMAP: {error}") from error
    def __exit__(self,*_):
        if self.conn:
            try:self.conn.logout()
            except Exception:pass
    def _search_uids(self,*criteria:str)->list[bytes]:
        status,data=self.conn.uid("search",None,*criteria)
        if status!="OK":raise RuntimeError("Busca IMAP falhou")
        return data[0].split() if data and data[0] else []
    def _messages_from_uids(self,uids:list[bytes]):
        self.last_found_count=len(uids);self.last_relevant_count=0
        for uid in uids:
            status,parts=self.conn.uid("fetch",uid,b"(BODY.PEEK[])")
            if status!="OK":continue
            raw=next((p[1] for p in parts if isinstance(p,tuple)),None)
            if not raw:continue
            msg=email.message_from_bytes(raw)
            sender=str(make_header(decode_header(msg.get("From",""))))
            sender_address=parseaddr(sender)[1].lower()
            if self.domains and not any(sender_address.endswith(d if d.startswith("@") else "@"+d) for d in self.domains):continue
            self.last_relevant_count+=1
            subject=str(make_header(decode_header(msg.get("Subject",""))))
            try:email_date=parsedate_to_datetime(msg.get("Date")).isoformat()
            except Exception:email_date=msg.get("Date","")
            yield MailMessage(uid.decode(),msg.get("Message-ID","" ).strip(),sender,subject,email_date,raw)
    def messages(self,limit:int=100):
        uids=self._search_uids("ALL")
        # UIDs são crescentes; a fatia final corresponde às mensagens mais recentes.
        return self._messages_from_uids(uids[-limit:] if limit>0 else uids)
    def messages_between(self,start_date:date,end_date:date):
        """Busca via IMAP o período inclusivo [start_date, end_date], sem limite de MAX_EMAILS_PER_RUN."""
        if end_date<start_date:raise ValueError("A data final deve ser igual ou posterior à data inicial")
        before=end_date+timedelta(days=1)
        criteria=(f"SINCE {_imap_date(start_date)}",f"BEFORE {_imap_date(before)}")
        return self._messages_from_uids(self._search_uids(*criteria))
    @staticmethod
    def save_pdf_attachments(message:MailMessage,directory:Path)->list[Path]:
        directory.mkdir(parents=True,exist_ok=True);msg=email.message_from_bytes(message.raw);saved=[]
        for part in msg.walk():
            if part.get_content_maintype()=="multipart":continue
            filename=part.get_filename()
            if not filename:continue
            filename=str(make_header(decode_header(filename)));payload=part.get_payload(decode=True)
            if payload and (filename.lower().endswith(".pdf") or part.get_content_type()=="application/pdf"):
                safe="".join(c if c.isalnum() or c in " ._-" else "_" for c in Path(filename).name).strip() or "anexo.pdf"
                target=directory/safe
                if target.exists():target=directory/f"{len(saved)+1}_{safe}"
                target.write_bytes(payload);saved.append(target)
        return saved
