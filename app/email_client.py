"""Acesso IMAP SSL, filtragem de remetentes e download de anexos PDF."""
import email, imaplib, time
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime,parseaddr
from pathlib import Path
from .logger import get_logger
log=get_logger()

@dataclass
class MailMessage:
    uid:str; message_id:str; sender:str; subject:str; date:str; raw:bytes

class EmailClient:
    def __init__(self, host:str, port:int, user:str, password:str, folder:str, domains:tuple[str,...], use_ssl:bool=True):
        self.host,self.port,self.user,self.password,self.folder,self.domains,self.use_ssl=host,port,user,password,folder,domains,use_ssl
        self.conn=None
    def __enter__(self):
        error=None
        for attempt in range(3):
            try:
                cls=imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4
                self.conn=cls(self.host,self.port,timeout=45); self.conn.login(self.user,self.password)
                status,_=self.conn.select(self.folder,readonly=True)
                if status!="OK": raise RuntimeError(f"Não foi possível selecionar pasta {self.folder}")
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
    def messages(self, limit:int=100):
        status,data=self.conn.uid("search",None,"ALL")
        if status!="OK":raise RuntimeError("Busca IMAP falhou")
        ids=data[0].split()[-limit:]
        for uid in ids:
            status,parts=self.conn.uid("fetch",uid,b"(BODY.PEEK[])")
            if status!="OK":continue
            raw=next((p[1] for p in parts if isinstance(p,tuple)),None)
            if not raw:continue
            msg=email.message_from_bytes(raw)
            sender=str(make_header(decode_header(msg.get("From",""))))
            sender_address=parseaddr(sender)[1].lower()
            if self.domains and not any(sender_address.endswith(d if d.startswith("@") else "@"+d) for d in self.domains):continue
            subject=str(make_header(decode_header(msg.get("Subject",""))))
            try:date=parsedate_to_datetime(msg.get("Date")).isoformat()
            except Exception:date=msg.get("Date","")
            yield MailMessage(uid.decode(),msg.get("Message-ID","").strip(),sender,subject,date,raw)
    @staticmethod
    def save_pdf_attachments(message:MailMessage, directory:Path)->list[Path]:
        directory.mkdir(parents=True,exist_ok=True); msg=email.message_from_bytes(message.raw); saved=[]
        for part in msg.walk():
            if part.get_content_maintype()=="multipart":continue
            filename=part.get_filename()
            if not filename:continue
            filename=str(make_header(decode_header(filename)))
            payload=part.get_payload(decode=True)
            if payload and (filename.lower().endswith(".pdf") or part.get_content_type()=="application/pdf"):
                safe="".join(c if c.isalnum() or c in " ._-" else "_" for c in Path(filename).name).strip() or "anexo.pdf"
                target=directory/safe
                if target.exists():target=directory/f"{len(saved)+1}_{safe}"
                target.write_bytes(payload); saved.append(target)
        return saved
