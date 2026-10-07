"""IMAP SSL com seleção inclusiva de datas, filtro e reconexão limitada por UID."""
import email,imaplib,time,socket
from dataclasses import dataclass
from datetime import date,timedelta
from email.header import decode_header,make_header
from email.utils import parsedate_to_datetime,parseaddr
from pathlib import Path
from .logger import get_logger
log=get_logger();MONTHS=("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")
class IMAPConnectionLost(RuntimeError):pass
def _imap_date(value:date)->str:return f"{value.day:02d}-{MONTHS[value.month-1]}-{value.year:04d}"
def _is_transport_error(exc:Exception)->bool:
    if isinstance(exc,(ConnectionError,ConnectionResetError,BrokenPipeError,TimeoutError,socket.timeout,imaplib.IMAP4.abort)):return True
    if isinstance(exc,imaplib.IMAP4.error):
        text=str(exc).casefold()
        return any(term in text for term in ("connection","reset","closed","socket","broken pipe","timeout","timed out","eof","abort"))
    return False
@dataclass
class MailMessage:
    uid:str;message_id:str;sender:str;subject:str;date:str;raw:bytes
class EmailClient:
    def __init__(self,host:str,port:int,user:str,password:str,folder:str,domains:tuple[str,...],use_ssl:bool=True,reconnect_delays:tuple[int,...]=(2,4,8)):
        self.host,self.port,self.user,self.password,self.folder,self.domains,self.use_ssl=host,port,user,password,folder,domains,use_ssl
        self.reconnect_delays=reconnect_delays;self.conn=None;self.last_found_count=0;self.last_relevant_count=0
    def _disconnect(self):
        conn=self.conn;self.conn=None
        if conn:
            sock=getattr(conn,"sock",None)
            try:
                if sock:sock.close()
                else:conn.logout()
            except Exception:pass
    def _connect_once(self):
        cls=imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4
        conn=cls(self.host,self.port,timeout=45)
        try:
            conn.login(self.user,self.password);status,_=conn.select(self.folder,readonly=True)
            if status!="OK":raise RuntimeError(f"Não foi possível selecionar pasta IMAP {self.folder}")
        except Exception:
            try:conn.logout()
            except Exception:pass
            raise
        self.conn=conn
    def __enter__(self):
        last=None
        for attempt in range(3):
            try:self._connect_once();return self
            except Exception as exc:
                last=exc
                if attempt<2:time.sleep(2*(attempt+1))
        raise IMAPConnectionLost(f"Falha inicial ao conectar/selecionar pasta IMAP: {last}") from last
    def __exit__(self,*_):self._disconnect()
    def _reconnect(self,cause:Exception):
        self._disconnect();last=cause
        for delay in self.reconnect_delays:
            log.warning("Conexão IMAP perdida; nova conexão em %ss (%s)",delay,cause)
            time.sleep(delay)
            try:self._connect_once();log.info("IMAP reconectado; pasta %s selecionada",self.folder);return
            except Exception as exc:last=exc
        raise IMAPConnectionLost(f"Reconexão IMAP esgotada; lote parcialmente processado e dados concluídos preservados: {last}") from last
    def _uid(self,*args):
        last=None
        for attempt in range(4):
            try:
                if self.conn is None:raise imaplib.IMAP4.abort("connection closed")
                return self.conn.uid(*args)
            except Exception as exc:
                if not _is_transport_error(exc):raise
                last=exc
                if attempt>=3:break
                self._reconnect(exc)
        raise IMAPConnectionLost(f"Falha de transporte IMAP após retries limitados no comando UID {args[0]}: {last}") from last
    def _search_uids(self,*criteria:str)->list[bytes]:
        status,data=self._uid("search",None,*criteria)
        if status!="OK":raise RuntimeError("Busca IMAP falhou")
        return data[0].split() if data and data[0] else []
    def _messages_from_uids(self,uids:list[bytes]):
        self.last_found_count=len(uids);self.last_relevant_count=0
        for uid in uids:
            status,parts=self._uid("fetch",uid,b"(BODY.PEEK[])")
            if status!="OK":continue
            raw=next((part[1] for part in parts if isinstance(part,tuple)),None)
            if not raw:continue
            msg=email.message_from_bytes(raw);sender=str(make_header(decode_header(msg.get("From",""))))
            sender_address=parseaddr(sender)[1].lower()
            if self.domains and not any(sender_address.endswith(domain if domain.startswith("@") else "@"+domain) for domain in self.domains):continue
            self.last_relevant_count+=1;subject=str(make_header(decode_header(msg.get("Subject",""))))
            try:email_date=parsedate_to_datetime(msg.get("Date")).isoformat()
            except Exception:email_date=msg.get("Date","")
            yield MailMessage(uid.decode(),msg.get("Message-ID","").strip(),sender,subject,email_date,raw)
    def messages(self,limit:int=100):
        uids=self._search_uids("ALL")
        return self._messages_from_uids(uids[-limit:] if limit>0 else uids)
    def messages_between(self,start_date:date,end_date:date):
        """IMAP [SINCE start, BEFORE end+1] (ambos os dias informados inclusivos)."""
        if end_date<start_date:raise ValueError("A data final deve ser igual ou posterior à data inicial")
        before=end_date+timedelta(days=1)
        return self._messages_from_uids(self._search_uids(f"SINCE {_imap_date(start_date)}",f"BEFORE {_imap_date(before)}"))
    @staticmethod
    def save_pdf_attachments(message:MailMessage,directory:Path)->list[Path]:
        directory.mkdir(parents=True,exist_ok=True);msg=email.message_from_bytes(message.raw);saved=[]
        for part in msg.walk():
            if part.get_content_maintype()=="multipart":continue
            filename=part.get_filename()
            if not filename:continue
            filename=str(make_header(decode_header(filename)));payload=part.get_payload(decode=True)
            if payload and (filename.lower().endswith(".pdf") or part.get_content_type()=="application/pdf"):
                safe="".join(char if char.isalnum() or char in " ._-" else "_" for char in Path(filename).name).strip() or "anexo.pdf"
                target=directory/safe
                if target.exists():target=directory/f"{len(saved)+1}_{safe}"
                target.write_bytes(payload);saved.append(target)
        return saved
