"""Orquestração; backfill altera só a seleção e reutiliza process_message()."""
import argparse,hashlib,json,shutil,sys,time
from pathlib import Path
from datetime import datetime,date,timezone
from .config import settings
from .logger import get_logger
from .email_client import EmailClient,MailMessage
from .attachment_processor import valid_pdfs,resolve_roles
from .pdf_processor import first_pages
from .openrouter_client import OpenRouterClient
from .validator import validate_policy,require_minimum
from .file_manager import sha256,publish
from .excel_robot_control import RobotControl
from .excel_apolices import update_workbook
log=get_logger()

class CountingOpenRouter:
    """Conta operações lógicas OpenRouter do lote para o resumo."""
    def __init__(self,client):self.client=client;self.classifications=0;self.analyses=0
    @property
    def calls(self):return self.classifications+self.analyses
    def classify(self,*args,**kwargs):self.classifications+=1;return self.client.classify(*args,**kwargs)
    def analyze(self,*args,**kwargs):self.analyses+=1;return self.client.analyze(*args,**kwargs)

def _client():
    names=[name.strip() for name in (settings.thi_names,settings.phas_names) if name.strip()]
    return OpenRouterClient(settings.openrouter_api_key,settings.openrouter_model,settings.openrouter_base_url,settings.openrouter_timeout,names)
def _test()->int:
    """Smoke test offline: não acessa e-mail nem serviços externos."""
    from .models import PolicyData,Evidence
    evidence={name:Evidence(valor=value,fonte="APOLICE",confianca=.95) for name,value in {
        "empresa_normalizada":"THI","orgao":"Órgão teste","numero_concorrencia_normalizado":"1-2026",
        "vigencia_data_inicial":date(2026,1,1),"vigencia_data_final":date(2026,12,31)}.items()}
    data=PolicyData(empresa_normalizada="THI",orgao="Órgão teste",numero_concorrencia_normalizado="1-2026",vigencia_data_inicial=date(2026,1,1),vigencia_data_final=date(2026,12,31),confianca_geral=.95,evidencias=evidence)
    require_minimum(data);log.info("Smoke test local concluído; validação estrutural e de confiança OK");return 0

def process_message(message:MailMessage,control:RobotControl,client=None,dry_run:bool=False,root_dir:Path|None=None,policies_excel:Path|None=None,backup_dir:Path|None=None,temp_root:Path|None=None,history_root:Path|None=None,mode:str|None=None)->str:
    """Baixa, interpreta, valida e registra um e-mail, mantendo rollback seguro."""
    client=client or _client();root_dir=root_dir or settings.root_dir;policies_excel=policies_excel or settings.policies_excel
    backup_dir=backup_dir or Path("backups");temp_root=temp_root or Path("data/temp");history_root=history_root or Path("data/historico")
    ident=hashlib.sha256((message.message_id or message.uid).encode()).hexdigest()[:24]
    if not control.can_retry(message.message_id,message.uid):
        log.warning("[%s] Limite de tentativas atingido; requer revisão manual",ident);return "IGNORADO"
    attempt=control.attempts(message.message_id,message.uid)+1
    process_id=control.begin(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,modelo_ia=settings.openrouter_model)
    run_mode=mode or ("DRY_RUN" if dry_run else "NORMAL")
    if dry_run and run_mode=="BACKFILL":run_mode="BACKFILL_DRY_RUN"
    log.info("[%s] Iniciando %s (tentativa %s)",process_id,run_mode,attempt)
    temp=temp_root/ident;temp.mkdir(parents=True,exist_ok=True);created_files=[];destination=None
    try:
        attachments=valid_pdfs(EmailClient.save_pdf_attachments(message,temp))
        log.info("[%s] %s PDFs válidos",process_id,len(attachments))
        if len(attachments)<2:raise ValueError("SEM_PDFS: Menos de dois PDFs válidos; revisão manual necessária")
        attachment_hashes={sha256(p) for p in attachments}
        already={h for row in control.rows() if row.get("status")=="SUCESSO" for h in (row.get("hash_apolice"),row.get("hash_boleto")) if h}
        if attachment_hashes and attachment_hashes.issubset(already):
            control.record(message_id=message.message_id,uid=message.uid,status="IGNORADO",erro="Todos os PDFs já constam como processados",modelo_ia=settings.openrouter_model)
            log.info("[%s] PDFs previamente processados; ignorado sem chamada OpenRouter",process_id);return "IGNORADO"
        roles=client.classify(attachments,[p.name for p in attachments]);policy,bill=resolve_roles(roles,attachments)
        phash,bhash=sha256(policy),sha256(bill)
        if control.already_processed("",{phash,bhash}):
            control.record(message_id=message.message_id,uid=message.uid,status="IGNORADO",hash_apolice=phash,hash_boleto=bhash,erro="Par apólice/boleto já processado",modelo_ia=settings.openrouter_model)
            log.info("[%s] Documentos já processados; ignorado",process_id);return "IGNORADO"
        log.info("[%s] Apólice e boleto identificados; enviando páginas 1-3 e boleto completo",process_id)
        policy_analysis=first_pages(policy,temp/"apolice_analise.pdf");result=client.analyze(policy_analysis,bill)
        history=history_root/process_id;history.mkdir(parents=True,exist_ok=True)
        (history/"resultado.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        (temp/"resultado.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        metadata={"id_processamento":process_id,"message_id":message.message_id,"uid":message.uid,"data_email":message.date,"remetente":message.sender,"assunto":message.subject,"modelo":settings.openrouter_model,"arquivos_analisados":[policy.name,bill.name],"timestamp_utc":datetime.now(timezone.utc).isoformat(),"modo_execucao":run_mode}
        (history/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        data=validate_policy(result);require_minimum(data)
        if dry_run:
            from .file_manager import build_destination,build_document_names
            log.info("[%s] DRY RUN: publicaria em %s, nomes=%s; Excel operacional e PDFs definitivos intactos",process_id,build_destination(root_dir,data),build_document_names(data))
            control.record(message_id=message.message_id,uid=message.uid,status="IGNORADO",hash_apolice=phash,hash_boleto=bhash,erro="DRY_RUN: análise concluída sem publicação",modelo_ia=settings.openrouter_model,id_processamento=process_id)
            return "DRY_RUN"
        destination,created_files=publish(root_dir,data,policy,bill,return_created=True)
        try:
            last_error=None
            for index in range(3):
                try:update_workbook(policies_excel,data,backup_dir);last_error=None;break
                except PermissionError as exc:
                    last_error=exc
                    if index<2:time.sleep(2**index)
            if last_error:raise last_error
        except Exception:
            for target in created_files:
                try:target.unlink(missing_ok=True)
                except OSError:log.exception("[%s] Rollback de PDF falhou: %s",process_id,target)
            raise
        control.record(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,hash_apolice=phash,hash_boleto=bhash,status="SUCESSO",modelo_ia=settings.openrouter_model,pasta_destino=str(destination),id_processamento=process_id)
        log.info("[%s] SUCESSO; destino=%s",process_id,destination)
        if not settings.keep_success_temp:shutil.rmtree(temp,ignore_errors=True)
        return "SUCESSO"
    except Exception as exc:
        log.exception("[%s] ERRO no processamento: %s",process_id,exc)
        try:control.record(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,status="ERRO",erro=str(exc)[:1000],modelo_ia=settings.openrouter_model,id_processamento=process_id,pasta_destino=str(destination) if destination else None)
        except Exception:log.exception("[%s] Não foi possível persistir o erro",process_id)
        return "SEM_PDFS" if str(exc).startswith("SEM_PDFS:") else "ERRO"

def run(dry_run:bool=False,backfill_period:tuple[date,date]|None=None)->int:
    dry_run=dry_run or settings.dry_run
    if not settings.email_user or not settings.email_password:raise RuntimeError("Preencha EMAIL_USER e EMAIL_PASSWORD no .env")
    if not settings.allowed_sender_domains:raise RuntimeError("ALLOWED_SENDER_DOMAINS deve conter ao menos um domínio autorizado")
    control=RobotControl(settings.robot_control,settings.robot_max_attempts)
    start,end=backfill_period if backfill_period else (None,None)
    mode="BACKFILL" if backfill_period else None
    with EmailClient(settings.email_host,settings.email_port,settings.email_user,settings.email_password,settings.email_folder,settings.allowed_sender_domains,settings.email_use_ssl) as mail:
        messages=mail.messages_between(start,end) if backfill_period else mail.messages(settings.max_emails_per_run)
        client=None;counts={"SUCESSO":0,"IGNORADO":0,"ERRO":0,"SEM_PDFS":0};had_relevant=False
        for message in messages:
            had_relevant=True
            prior=control.find(message.message_id,message.uid)
            if prior and prior.get("status")=="SUCESSO":counts["IGNORADO"]+=1;continue
            if not control.can_retry(message.message_id,message.uid):
                log.warning("Mensagem %s excedeu tentativas; ignorada para revisão",message.message_id or message.uid);counts["IGNORADO"]+=1;continue
            if client is None:client=CountingOpenRouter(_client())
            try:result=process_message(message,control,client=client,dry_run=dry_run,mode=mode)
            except Exception as exc:
                log.exception("Falha inesperada no e-mail %s; continuando lote",message.message_id or message.uid)
                try:control.record(message_id=message.message_id,uid=message.uid,status="ERRO",erro=str(exc)[:1000],modelo_ia=settings.openrouter_model)
                except Exception:log.exception("Não foi possível registrar falha inesperada no controle")
                result="ERRO"
            counts[result]=counts.get(result,0)+1
        found=mail.last_found_count;relevant=mail.last_relevant_count
        log.info("Busca IMAP: %s mensagens candidatas, %s remetentes relevantes",found,relevant)
    if not had_relevant:
        if backfill_period:print("Nenhum e-mail relevante encontrado no período informado.")
        else:log.info("Nenhum e-mail relevante encontrado")
        return 0
    calls=client.calls if client else 0
    if backfill_period:
        print("BACKFILL FINALIZADO")
        print(f"Período: {start:%d/%m/%Y} → {end:%d/%m/%Y} (inclusivo)")
        print(f"E-mails encontrados: {found}\nE-mails relevantes: {relevant}")
        print(f"Processados com sucesso: {counts['SUCESSO']}\nIgnorados/revisão: {counts['IGNORADO']+counts.get('DRY_RUN',0)}\nCom erro: {counts['ERRO']}\nSem PDFs válidos: {counts['SEM_PDFS']}")
        print(f"OpenRouter: {client.analyses if client else 0} análises; {client.classifications if client else 0} classificações\nHistórico: data/historico/")
    else:log.info("Execução encerrada: %s; chamadas OpenRouter lógicas=%s",counts,calls)
    return 0

def parse_backfill_date(value:str)->date:
    try:return datetime.strptime(value,"%d/%m/%Y").date()
    except ValueError as exc:raise argparse.ArgumentTypeError("Data inválida; use DD/MM/AAAA") from exc

def main()->int:
    parser=argparse.ArgumentParser(description="Robô local de controle de apólices THI/PHAS")
    parser.add_argument("--test",action="store_true",help="smoke test offline")
    parser.add_argument("--dry-run",action="store_true",help="analisa e valida sem publicar documentos ou alterar Excel operacional")
    parser.add_argument("--backfill",action="store_true",help="processa e-mails de um período histórico inclusivo")
    parser.add_argument("--inicio",type=parse_backfill_date,help="data inicial DD/MM/AAAA (backfill)")
    parser.add_argument("--fim",type=parse_backfill_date,help="data final inclusiva DD/MM/AAAA (backfill)")
    args=parser.parse_args()
    if args.backfill and (args.inicio is None or args.fim is None):parser.error("--backfill exige --inicio e --fim no formato DD/MM/AAAA")
    if not args.backfill and (args.inicio is not None or args.fim is not None):parser.error("--inicio e --fim só podem ser usados com --backfill")
    if args.backfill and args.fim<args.inicio:parser.error("--fim deve ser igual ou posterior a --inicio")
    if args.test and (args.backfill or args.dry_run):parser.error("--test offline não pode ser combinado com --backfill ou --dry-run")
    try:return _test() if args.test else run(args.dry_run,(args.inicio,args.fim) if args.backfill else None)
    except Exception as exc:log.exception("Execução interrompida: %s",exc);return 1
if __name__=="__main__":sys.exit(main())
