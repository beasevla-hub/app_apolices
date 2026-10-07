"""Orquestração do robô; cada mensagem é tratada em process_message()."""
import argparse,hashlib,json,shutil,sys,time
from pathlib import Path
from datetime import datetime,timezone
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

def _client():
    names=[name.strip() for name in (settings.thi_names,settings.phas_names) if name.strip()]
    return OpenRouterClient(settings.openrouter_api_key,settings.openrouter_model,settings.openrouter_base_url,settings.openrouter_timeout,names)
def _test()->int:
    """Smoke test offline: não acessa e-mail nem serviços externos."""
    from .models import PolicyData
    from datetime import date
    from .models import Evidence
    evidence={name:Evidence(valor=value,fonte="APOLICE",confianca=.95) for name,value in {
        "empresa_normalizada":"THI","orgao":"Órgão teste","numero_concorrencia_normalizado":"1-2026",
        "vigencia_data_inicial":date(2026,1,1),"vigencia_data_final":date(2026,12,31)}.items()}
    data=PolicyData(empresa_normalizada="THI",orgao="Órgão teste",numero_concorrencia_normalizado="1-2026",vigencia_data_inicial=date(2026,1,1),vigencia_data_final=date(2026,12,31),confianca_geral=.95,evidencias=evidence)
    require_minimum(data);log.info("Smoke test local concluído; validação estrutural e de confiança OK");return 0

def process_message(message:MailMessage,control:RobotControl,client=None,dry_run:bool=False,root_dir:Path|None=None,policies_excel:Path|None=None,backup_dir:Path|None=None,temp_root:Path|None=None,history_root:Path|None=None)->str:
    """Baixa, interpreta, valida e registra um único e-mail sem alterar dados manuais."""
    client=client or _client();root_dir=root_dir or settings.root_dir;policies_excel=policies_excel or settings.policies_excel
    backup_dir=backup_dir or Path("backups");temp_root=temp_root or Path("data/temp");history_root=history_root or Path("data/historico")
    ident=hashlib.sha256((message.message_id or message.uid).encode()).hexdigest()[:24]
    if not control.can_retry(message.message_id,message.uid):
        log.warning("[%s] Limite de tentativas atingido; requer revisão manual",ident);return "ERRO"
    prior=control.find(message.message_id,message.uid);attempt=(control.attempts(message.message_id,message.uid)+1)
    process_id=control.begin(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,modelo_ia=settings.openrouter_model)
    log.info("[%s] Iniciando processamento (tentativa %s)",process_id,attempt)
    temp=temp_root/ident;temp.mkdir(parents=True,exist_ok=True);created_files=[];destination=None;history=None
    try:
        attachments=valid_pdfs(EmailClient.save_pdf_attachments(message,temp))
        log.info("[%s] %s PDFs válidos",process_id,len(attachments))
        if len(attachments)<2:raise ValueError("Menos de dois PDFs válidos; revisão manual necessária")
        attachment_hashes={sha256(p) for p in attachments}
        already={h for row in control.rows() if row.get("status")=="SUCESSO" for h in (row.get("hash_apolice"),row.get("hash_boleto")) if h}
        if attachment_hashes and attachment_hashes.issubset(already):
            control.record(message_id=message.message_id,uid=message.uid,status="IGNORADO",erro="Todos os PDFs já constam como processados",modelo_ia=settings.openrouter_model)
            log.info("[%s] Todos os PDFs já processados; ignorado sem chamada de IA",process_id);return "IGNORADO"
        roles=client.classify(attachments,[p.name for p in attachments]);policy,bill=resolve_roles(roles,attachments)
        phash,bhash=sha256(policy),sha256(bill)
        if control.already_processed("",{phash,bhash}):
            control.record(message_id=message.message_id,uid=message.uid,status="IGNORADO",hash_apolice=phash,hash_boleto=bhash,erro="Par apólice/boleto já processado",modelo_ia=settings.openrouter_model)
            log.info("[%s] Documentos já processados; ignorado",process_id);return "IGNORADO"
        log.info("[%s] Apólice e boleto identificados; enviando páginas 1-3 e boleto completo",process_id)
        policy_analysis=first_pages(policy,temp/"apolice_analise.pdf")
        result=client.analyze(policy_analysis,bill)
        history=history_root/process_id;history.mkdir(parents=True,exist_ok=True)
        (history/"resultado.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        (temp/"resultado.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        metadata={"id_processamento":process_id,"message_id":message.message_id,"uid":message.uid,"data_email":message.date,"remetente":message.sender,"assunto":message.subject,"modelo":settings.openrouter_model,"arquivos_analisados":[policy.name,bill.name],"timestamp_utc":datetime.now(timezone.utc).isoformat()}
        (history/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        data=validate_policy(result)
        require_minimum(data)
        if dry_run:
            from .file_manager import build_destination,build_document_names
            log.info("[%s] DRY RUN: publicaria em %s, nomes=%s; Excel e PDFs definitivos intactos",process_id,build_destination(root_dir,data),build_document_names(data))
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
        return "ERRO"

def run(dry_run:bool=False)->int:
    dry_run=dry_run or settings.dry_run
    if not settings.email_user or not settings.email_password:raise RuntimeError("Preencha EMAIL_USER e EMAIL_PASSWORD no .env")
    if not settings.openrouter_api_key:raise RuntimeError("Preencha OPENROUTER_API_KEY no .env; --dry-run também analisa documentos reais")
    control=RobotControl(settings.robot_control,settings.robot_max_attempts)
    with EmailClient(settings.email_host,settings.email_port,settings.email_user,settings.email_password,settings.email_folder,settings.allowed_sender_domains,settings.email_use_ssl) as mail:
        messages=list(mail.messages(settings.max_emails_per_run));log.info("%s e-mails relevantes encontrados",len(messages))
        counts={}
        for message in messages:
            prior=control.find(message.message_id,message.uid)
            if prior and prior.get("status")=="SUCESSO":continue
            if not control.can_retry(message.message_id,message.uid):
                log.warning("Mensagem %s excedeu tentativas; ignorada para revisão",message.message_id or message.uid);continue
            result=process_message(message,control,dry_run=dry_run)
            counts[result]=counts.get(result,0)+1
    log.info("Execução encerrada: %s",counts);return 0

def main()->int:
    parser=argparse.ArgumentParser(description="Robô local de controle de apólices THI/PHAS")
    parser.add_argument("--test",action="store_true",help="smoke test offline")
    parser.add_argument("--dry-run",action="store_true",help="analisa e valida e-mails reais sem publicar nem atualizar o Excel operacional")
    args=parser.parse_args()
    try:return _test() if args.test else run(args.dry_run)
    except Exception as exc:log.exception("Execução interrompida: %s",exc);return 1
if __name__=="__main__":sys.exit(main())
