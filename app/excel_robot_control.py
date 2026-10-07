"""Planilha técnica de idempotência, tentativas e auditoria do robô."""
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import os
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill
HEADERS=["message_id","uid","data_email","remetente","assunto","hash_apolice","hash_boleto","status","tentativas","modelo_ia","data_ultima_tentativa","data_processamento","erro","pasta_destino","id_processamento"]
class RobotControl:
    def __init__(self,path:Path,max_attempts:int=5):self.path=Path(path);self.max_attempts=max_attempts
    def _open(self):
        if self.path.exists():
            wb=load_workbook(self.path)
            if "EMAILS_PROCESSADOS" not in wb.sheetnames:raise ValueError("Aba EMAILS_PROCESSADOS ausente no controle do robô")
            ws=wb["EMAILS_PROCESSADOS"]
            current={str(ws.cell(1,c).value):c for c in range(1,ws.max_column+1) if ws.cell(1,c).value}
            for name in HEADERS:
                if name not in current:ws.cell(1,ws.max_column+1,name)
            return wb
        wb=Workbook();ws=wb.active;ws.title="EMAILS_PROCESSADOS";ws.append(HEADERS)
        for c in ws[1]:c.font=Font(bold=True,color="FFFFFF");c.fill=PatternFill("solid",fgColor="17365D")
        ws.freeze_panes="A2";ws.auto_filter.ref=f"A1:O1";return wb
    def rows(self):
        wb=self._open();ws=wb["EMAILS_PROCESSADOS"];headers={str(ws.cell(1,c).value):c for c in range(1,ws.max_column+1) if ws.cell(1,c).value}
        result=[]
        for row in range(2,ws.max_row+1):
            item={key:ws.cell(row,col).value for key,col in headers.items()}
            if any(v is not None for v in item.values()):result.append(item)
        if not self.path.exists():self.path.parent.mkdir(parents=True,exist_ok=True);wb.save(self.path)
        return result
    def find(self,message_id:str,uid:str=""):
        return next((r for r in self.rows() if (message_id and r.get("message_id")==message_id) or (uid and str(r.get("uid"))==str(uid))),None)
    def already_processed(self,message_id:str,hashes:set[str])->bool:
        def same_documents(row):
            stored={row.get("hash_apolice"),row.get("hash_boleto")}-{None,""}
            return bool(hashes) and hashes.issubset(stored)
        return any(r.get("status")=="SUCESSO" and ((message_id and r.get("message_id")==message_id) or same_documents(r)) for r in self.rows())
    def attempts(self,message_id:str,uid:str="")->int:
        record=self.find(message_id,uid);return int(record.get("tentativas") or 0) if record else 0
    def can_retry(self,message_id:str,uid:str="")->bool:
        row=self.find(message_id,uid)
        return not row or row.get("status")!="SUCESSO" and int(row.get("tentativas") or 0)<self.max_attempts
    def begin(self,**data)->str:
        process_id=data.get("id_processamento") or uuid4().hex[:12].upper()
        data["status"]="PROCESSANDO";data["id_processamento"]=process_id;data["increment_attempt"]=True
        self.record(**data)
        return process_id
    def record(self,**data):
        self.path.parent.mkdir(parents=True,exist_ok=True);wb=self._open();ws=wb["EMAILS_PROCESSADOS"]
        headers={str(ws.cell(1,c).value):c for c in range(1,ws.max_column+1) if ws.cell(1,c).value}
        mid=data.get("message_id","");uid=data.get("uid","")
        row_num=next((i for i in range(2,ws.max_row+1) if (mid and ws.cell(i,headers["message_id"]).value==mid) or (uid and str(ws.cell(i,headers["uid"]).value)==str(uid))),None)
        if row_num is None:row_num=ws.max_row+1
        old_attempt=int(ws.cell(row_num,headers["tentativas"]).value or 0) if row_num<=ws.max_row else 0
        values={k:data.get(k) for k in HEADERS if k in data}
        if data.get("increment_attempt"):values["tentativas"]=old_attempt+1
        elif "tentativas" not in values and old_attempt:values["tentativas"]=old_attempt
        values.setdefault("data_ultima_tentativa",datetime.now().isoformat(timespec="seconds"))
        if values.get("status")=="SUCESSO":values["data_processamento"]=datetime.now().isoformat(timespec="seconds")
        for key,value in values.items():
            if key in headers:ws.cell(row_num,headers[key]).value=value
        temp=self.path.with_name(self.path.stem+".tmp"+self.path.suffix)
        try:wb.save(temp);load_workbook(temp,read_only=True).close();os.replace(temp,self.path)
        except Exception:
            if temp.exists():temp.unlink()
            raise
