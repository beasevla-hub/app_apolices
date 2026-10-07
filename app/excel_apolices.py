"""Atualização conservadora do Excel operacional preservando formato e colunas manuais."""
from pathlib import Path
from datetime import datetime
import os,shutil
import unicodedata
from copy import copy
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill
from openpyxl.worksheet.table import Table,TableStyleInfo
from .models import PolicyData
ROBOT_MANAGED_COLUMNS=["ÓRGÃO","EMPRESA","Nº CONCORRÊNCIA/EDITAL","PROCESSO SEI","OBJETO","VIGÊNCIA DATA INICIAL","VIGÊNCIA DATA FINAL","VALOR DO PRÊMIO","Nº REGISTRO DA SUSEP","Nº DA LINHA DIGITÁVEL DO BOLETO"]
SHEET_NAME="APÓLICES"
def backup_file(path:Path,backup_dir:Path)->Path|None:
    if not path.exists():return None
    backup_dir.mkdir(parents=True,exist_ok=True)
    dest=backup_dir/f"controle_apolices_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx"
    shutil.copy2(path,dest)
    return dest

def _norm(value):
    text=str(value or "").strip().casefold()
    return "".join(ch for ch in unicodedata.normalize("NFKD",text) if not unicodedata.combining(ch))
def _company_matches(existing:str,normalized:str)->bool:
    value=_norm(existing); code=_norm(normalized)
    return value==code or value.startswith(code+" ") or value.startswith(code+"-")
def _copy_row_style(ws,source_row:int,target_row:int)->None:
    if source_row<1:return
    for col in range(1,ws.max_column+1):
        src,dst=ws.cell(source_row,col),ws.cell(target_row,col)
        if src.has_style:dst._style=copy(src._style)
        if src.number_format:dst.number_format=src.number_format
        if src.alignment:dst.alignment=copy(src.alignment)
        if src.protection:dst.protection=copy(src.protection)
    if source_row in ws.row_dimensions:ws.row_dimensions[target_row].height=ws.row_dimensions[source_row].height

def update_workbook(path:Path,data:PolicyData,backup_dir:Path)->str:
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        # Backup completo antes de carregar/modificar e com nome único.
        backup_file(path,backup_dir);wb=load_workbook(path)
        if SHEET_NAME not in wb.sheetnames:raise ValueError(f"A aba {SHEET_NAME} não foi encontrada; workbook preservado")
        ws=wb[SHEET_NAME]
    else:
        wb=Workbook();ws=wb.active;ws.title=SHEET_NAME;ws.append(ROBOT_MANAGED_COLUMNS)
        for cell in ws[1]:cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="17365D")
        ws.freeze_panes="A2"
    header={str(ws.cell(1,c).value).strip():c for c in range(1,ws.max_column+1) if ws.cell(1,c).value is not None}
    if not header:raise ValueError("Cabeçalho operacional inválido; workbook preservado")
    # Colunas gerenciadas faltantes são acrescentadas sem mover/remover conteúdo existente.
    for name in ROBOT_MANAGED_COLUMNS:
        if name not in header:
            col=ws.max_column+1;ws.cell(1,col,name);header[name]=col
    company=data.empresa_normalizada or data.tipo_empresa
    process=_norm(data.processo_sei);number=_norm(data.numero_concorrencia_normalizado);org=_norm(data.orgao_normalizado or data.orgao)
    if not company or not number or not (process or org):raise ValueError("Chave lógica insuficiente; revisão manual necessária")
    matches=[]
    for r in range(2,ws.max_row+1):
        existing_company=ws.cell(r,header["EMPRESA"]).value
        existing_proc=_norm(ws.cell(r,header["PROCESSO SEI"]).value)
        existing_num=_norm(ws.cell(r,header["Nº CONCORRÊNCIA/EDITAL"]).value)
        existing_org=_norm(ws.cell(r,header["ÓRGÃO"]).value)
        number_matches=existing_num in {number,_norm(data.numero_concorrencia_original)}
        primary=process and existing_proc and process==existing_proc and number_matches
        fallback=number_matches and org and existing_org==org
        if _company_matches(existing_company,company) and (primary or fallback):matches.append(r)
    if len(matches)>1:raise ValueError("POSSIVEL_DUPLICATA: múltiplas linhas correspondem à chave; sem alteração")
    existing=bool(matches);row=matches[0] if existing else ws.max_row+1
    if not existing and ws.max_row>=2:_copy_row_style(ws,ws.max_row,row)
    values={"ÓRGÃO":data.orgao,"EMPRESA":data.empresa or company,"Nº CONCORRÊNCIA/EDITAL":data.numero_concorrencia_original or data.numero_concorrencia_normalizado,"PROCESSO SEI":data.processo_sei,"OBJETO":data.objeto,"VIGÊNCIA DATA INICIAL":data.vigencia_data_inicial,"VIGÊNCIA DATA FINAL":data.vigencia_data_final,"VALOR DO PRÊMIO":data.valor_premio,"Nº REGISTRO DA SUSEP":data.numero_registro_susep,"Nº DA LINHA DIGITÁVEL DO BOLETO":data.linha_digitavel_boleto}
    for name,value in values.items():
        if value is None:continue  # null da IA nunca apaga informação existente
        cell=ws.cell(row,header[name]);cell.value=value
        if name.startswith("VIGÊNCIA"):cell.number_format="dd/mm/yyyy"
        elif name=="VALOR DO PRÊMIO":cell.number_format='R$ #,##0.00'
        elif name=="Nº DA LINHA DIGITÁVEL DO BOLETO":cell.number_format="@"
    ws.auto_filter.ref=ws.dimensions
    if ws.freeze_panes is None:ws.freeze_panes="A2"
    for name,col in header.items():
        if name in ROBOT_MANAGED_COLUMNS and ws.column_dimensions[ws.cell(1,col).column_letter].width is None:
            ws.column_dimensions[ws.cell(1,col).column_letter].width=max(18,min(48,len(name)+4))
    # Não altera referências de tabelas/filtros/validações já existentes.
    if ws.max_row>=2 and ws.tables:
        for table in ws.tables.values():table.ref=ws.dimensions
    elif ws.max_row>=2:
        heads=[ws.cell(1,c).value for c in range(1,ws.max_column+1)]
        if all(heads) and len(set(map(str,heads)))==len(heads):
            table=Table(displayName="ApolicesTable",ref=ws.dimensions);table.tableStyleInfo=TableStyleInfo(name="TableStyleMedium2",showRowStripes=True);ws.add_table(table)
    temp=path.with_name(path.stem+".tmp"+path.suffix)
    try:
        wb.save(temp);check=load_workbook(temp,read_only=True);check.close();os.replace(temp,path)
    except Exception:
        if temp.exists():temp.unlink()
        raise
    return "ATUALIZADO" if existing else "ADICIONADO"
