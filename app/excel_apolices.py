"""Atualização do Excel operacional sem reconfigurar layout humano existente."""
from pathlib import Path
from datetime import datetime
import os,shutil,unicodedata
from copy import copy
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill
from openpyxl.worksheet.table import Table,TableStyleInfo
from .models import PolicyData
ROBOT_MANAGED_COLUMNS=["ÓRGÃO","EMPRESA","Nº CONCORRÊNCIA/EDITAL","PROCESSO SEI","OBJETO","VIGÊNCIA DATA INICIAL","VIGÊNCIA DATA FINAL","VALOR DO PRÊMIO","Nº REGISTRO DA SUSEP","Nº DA LINHA DIGITÁVEL DO BOLETO","LOTE"]
SHEET_NAME="APÓLICES"
HEADER_ALIASES={
 "ÓRGÃO":("ÓRGÃO","ORGAO","NOME DO ORGAO","ORGAO CONTRATANTE"),
 "EMPRESA":("EMPRESA","SEGURADO","RAZAO SOCIAL"),
 "Nº CONCORRÊNCIA/EDITAL":("Nº CONCORRÊNCIA/EDITAL","Nº DA CONCORRÊNCIA/EDITAL","NUMERO CONCORRENCIA EDITAL","N CONCORRENCIA EDITAL","NUMERO DA CONCORRENCIA","CONCORRENCIA","EDITAL","NUMERO DA LICITACAO"),
 "PROCESSO SEI":("PROCESSO SEI","Nº PROCESSO SEI","Nº DO PROCESSO SEI","NUMERO DO PROCESSO SEI","SEI","NUMERO SEI"),
 "OBJETO":("OBJETO","OBJETO DA LICITACAO"),
 "VIGÊNCIA DATA INICIAL":("VIGÊNCIA DATA INICIAL","VIGENCIA INICIAL","INICIO VIGENCIA","DATA INICIAL"),
 "VIGÊNCIA DATA FINAL":("VIGÊNCIA DATA FINAL","VIGENCIA FINAL","FIM VIGENCIA","DATA FINAL"),
 "VALOR DO PRÊMIO":("VALOR DO PRÊMIO","VALOR PREMIO","PREMIO","VALOR DO SEGURO"),
 "Nº REGISTRO DA SUSEP":("Nº REGISTRO DA SUSEP","NUMERO REGISTRO SUSEP","REGISTRO SUSEP","SUSEP"),
 "Nº DA LINHA DIGITÁVEL DO BOLETO":("Nº DA LINHA DIGITÁVEL DO BOLETO","LINHA DIGITAVEL DO BOLETO","LINHA DIGITAVEL BOLETO","LINHA DIGITAVEL","CODIGO DE BARRAS"),
 "LOTE":("LOTE","Nº LOTE","Nº DO LOTE","NUMERO DO LOTE","NÚMERO DO LOTE","NUMERO LOTE")}
def backup_file(path:Path,backup_dir:Path)->Path|None:
    if not path.exists():return None
    backup_dir.mkdir(parents=True,exist_ok=True);dest=backup_dir/f"controle_apolices_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx";shutil.copy2(path,dest);return dest
def _norm(value):
    text=str(value or "").strip().casefold()
    return "".join(ch for ch in unicodedata.normalize("NFKD",text) if not unicodedata.combining(ch))
def _norm_lot(value):
    text=" ".join(_norm(value).split())
    return text[5:].strip() if text.startswith("lote ") else text
def _header_norm(value)->str:
    text=_norm(value)
    return "".join(ch for ch in text if ch.isalnum())
def _aliases():return {_header_norm(alias):canonical for canonical,items in HEADER_ALIASES.items() for alias in items}
def _header_map(ws):
    aliases=_aliases();found={}
    for col in range(1,ws.max_column+1):
        raw=ws.cell(1,col).value
        if raw is None:continue
        canonical=aliases.get(_header_norm(raw))
        if canonical:
            if canonical in found:raise ValueError(f"Cabeçalho ambíguo para {canonical}: colunas {found[canonical]} e {col}")
            found[canonical]=col
    return found
def _company_matches(existing,normalized)->bool:
    value=_norm(existing);code=_norm(normalized)
    return value==code or value.startswith(code+" ") or value.startswith(code+"-")
def _copy_row_style(ws,source_row:int,target_row:int)->None:
    for col in range(1,ws.max_column+1):
        src,dst=ws.cell(source_row,col),ws.cell(target_row,col)
        if src.has_style:dst._style=copy(src._style)
        if src.number_format:dst.number_format=src.number_format
        if src.alignment:dst.alignment=copy(src.alignment)
        if src.protection:dst.protection=copy(src.protection)
    if ws.row_dimensions[source_row].height is not None:ws.row_dimensions[target_row].height=ws.row_dimensions[source_row].height
def _available_row(ws)->int:
    for row in range(2,ws.max_row+1):
        if all(ws.cell(row,col).value is None for col in range(1,ws.max_column+1)):return row
    return ws.max_row+1
def update_workbook(path:Path,data:PolicyData,backup_dir:Path)->str:
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);is_new=not path.exists()
    if not is_new:
        backup_file(path,backup_dir);wb=load_workbook(path)
        if SHEET_NAME not in wb.sheetnames:raise ValueError(f"A aba {SHEET_NAME} não foi encontrada; workbook preservado")
        ws=wb[SHEET_NAME]
    else:
        wb=Workbook();ws=wb.active;ws.title=SHEET_NAME;ws.append(ROBOT_MANAGED_COLUMNS)
        for cell in ws[1]:cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="17365D")
        ws.freeze_panes="A2"
    headers=_header_map(ws)
    required=[name for name in ROBOT_MANAGED_COLUMNS if name!="LOTE"]
    missing=[name for name in required if name not in headers]
    if missing:raise ValueError("Cabeçalhos operacionais ausentes/irreconhecíveis: "+", ".join(missing))
    if "LOTE" not in headers:
        if not is_new:
            col=ws.max_column+1;ws.cell(1,col,"LOTE")
            if col>1 and ws.cell(1,col-1).has_style:ws.cell(1,col)._style=copy(ws.cell(1,col-1)._style)
            headers["LOTE"]=col
        else:headers=_header_map(ws)
    company=data.empresa_normalizada or data.tipo_empresa
    process=_norm(data.processo_sei);number=_norm(data.numero_concorrencia_normalizado);org=_norm(data.orgao_normalizado or data.orgao);lot=_norm_lot(data.lote)
    if not company or not number or not (process or org):raise ValueError("Chave lógica insuficiente; revisão manual necessária")
    matches=[]
    for row in range(2,ws.max_row+1):
        existing_company=ws.cell(row,headers["EMPRESA"]).value
        existing_proc=_norm(ws.cell(row,headers["PROCESSO SEI"]).value)
        existing_num=_norm(ws.cell(row,headers["Nº CONCORRÊNCIA/EDITAL"]).value)
        existing_org=_norm(ws.cell(row,headers["ÓRGÃO"]).value)
        existing_lot=_norm_lot(ws.cell(row,headers["LOTE"]).value)
        number_matches=existing_num in {number,_norm(data.numero_concorrencia_original)}
        lot_matches=existing_lot==lot
        if process:logical=bool(existing_proc and process==existing_proc and number_matches and lot_matches)
        else:logical=bool(not existing_proc and number_matches and org and existing_org==org and lot_matches)
        if _company_matches(existing_company,company) and logical:matches.append(row)
    if len(matches)>1:raise ValueError("POSSIVEL_DUPLICATA: múltiplas linhas correspondem à chave; sem alteração")
    existing=bool(matches);row=matches[0] if existing else _available_row(ws)
    if not existing and row==ws.max_row+1 and row>2:_copy_row_style(ws,row-1,row)
    values={"ÓRGÃO":data.orgao,"EMPRESA":data.empresa or company,"Nº CONCORRÊNCIA/EDITAL":data.numero_concorrencia_original or data.numero_concorrencia_normalizado,"PROCESSO SEI":data.processo_sei,"OBJETO":data.objeto,"VIGÊNCIA DATA INICIAL":data.vigencia_data_inicial,"VIGÊNCIA DATA FINAL":data.vigencia_data_final,"VALOR DO PRÊMIO":data.valor_premio,"Nº REGISTRO DA SUSEP":data.numero_registro_susep,"Nº DA LINHA DIGITÁVEL DO BOLETO":data.linha_digitavel_boleto,"LOTE":data.lote}
    for name,value in values.items():
        if value is not None:ws.cell(row,headers[name]).value=value
    if is_new and ws.auto_filter.ref is None:ws.auto_filter.ref=ws.dimensions
    if is_new and ws.max_row>=2:
        heads=[ws.cell(1,col).value for col in range(1,ws.max_column+1)]
        if all(heads) and len(set(map(str,heads)))==len(heads):
            table=Table(displayName="ApolicesTable",ref=ws.dimensions);table.tableStyleInfo=TableStyleInfo(name="TableStyleMedium2",showRowStripes=True);ws.add_table(table)
    temp=path.with_name(path.stem+".tmp"+path.suffix)
    try:
        wb.save(temp);check=load_workbook(temp,read_only=True);check.close();os.replace(temp,path)
    except Exception:
        if temp.exists():temp.unlink()
        raise
    return "ATUALIZADO" if existing else "ADICIONADO"
