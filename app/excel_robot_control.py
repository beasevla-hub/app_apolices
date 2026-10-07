"""Planilha técnica de idempotência e auditoria do robô."""
from pathlib import Path
from datetime import datetime
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill
HEADERS=["message_id","uid","data_email","remetente","assunto","hash_apolice","hash_boleto","status","data_processamento","erro","pasta_destino"]
class RobotControl:
    def __init__(self,path:Path):self.path=Path(path)
    def _open(self):
        if self.path.exists():return load_workbook(self.path)
        wb=Workbook();ws=wb.active;ws.title="EMAILS_PROCESSADOS";ws.append(HEADERS)
        for c in ws[1]:c.font=Font(bold=True,color="FFFFFF");c.fill=PatternFill("solid",fgColor="17365D")
        ws.freeze_panes="A2";ws.auto_filter.ref=f"A1:{chr(64+len(HEADERS))}1";return wb
    def rows(self):
        wb=self._open();ws=wb["EMAILS_PROCESSADOS"]
        result=[dict(zip(HEADERS,row)) for row in ws.iter_rows(min_row=2,values_only=True) if any(v is not None for v in row)]
        if not self.path.exists():self.path.parent.mkdir(parents=True,exist_ok=True);wb.save(self.path)
        return result
    def already_processed(self,message_id:str,hashes:set[str])->bool:
        return any(r.get("status")=="SUCESSO" and ((message_id and r.get("message_id")==message_id) or hashes.intersection({r.get("hash_apolice"),r.get("hash_boleto")})) for r in self.rows())
    def record(self,**data):
        self.path.parent.mkdir(parents=True,exist_ok=True);wb=self._open();ws=wb["EMAILS_PROCESSADOS"]
        mid=data.get("message_id",""); uid=data.get("uid","")
        row_num=next((i for i in range(2,ws.max_row+1) if (mid and ws.cell(i,1).value==mid) or (uid and ws.cell(i,2).value==uid)),None)
        values=[data.get(k) for k in HEADERS[:8]]+[datetime.now().isoformat(timespec="seconds"),data.get("erro"),data.get("pasta_destino")]
        if row_num: 
            for col,val in enumerate(values,1):ws.cell(row_num,col).value=val
        else:ws.append(values)
        wb.save(self.path)
