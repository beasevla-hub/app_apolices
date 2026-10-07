"""Ponto de entrada e orquestração do robô."""
import argparse,hashlib,json,shutil,sys,time
from pathlib import Path
from .config import settings
from .logger import get_logger
from .email_client import EmailClient
from .attachment_processor import valid_pdfs,resolve_roles
from .pdf_processor import first_pages
from .openrouter_client import OpenRouterClient
from .validator import validate_policy,require_minimum
from .file_manager import sha256,publish
from .excel_robot_control import RobotControl
from .excel_apolices import update_workbook
log=get_logger()

def _client():return OpenRouterClient(settings.openrouter_api_key,settings.openrouter_model,settings.openrouter_base_url,settings.openrouter_timeout)
def _test()->int:
    """Offline smoke test; never requires credentials or external services."""
    from .models import PolicyData
    from datetime import date
    data=PolicyData(tipo_empresa="THI",orgao="Órgão teste",numero_concorrencia_normalizado="1-2026",vigencia_data_inicial=date(2026,1,1),vigencia_data_final=date(2026,12,31),confianca_geral=.9)
    require_minimum(data);log.info("Modo de teste local concluído; validação de modelo OK")
    return 0

def run(dry_run:bool=False)->int:
    dry_run=dry_run or settings.dry_run
    if not settings.email_user or not settings.email_password:raise RuntimeError("Preencha EMAIL_USER e EMAIL_PASSWORD no .env")
    control=RobotControl(settings.robot_control)
    processed=control.rows()
    known_hashes={h for r in processed if r.get("status")=="SUCESSO" for h in (r.get("hash_apolice"),r.get("hash_boleto")) if h}
    if not dry_run and (not settings.openrouter_api_key):raise RuntimeError("Preencha OPENROUTER_API_KEY no .env")
    count=0
    with EmailClient(settings.email_host,settings.email_port,settings.email_user,settings.email_password,settings.email_folder,settings.allowed_sender_domains,settings.email_use_ssl) as mail:
        messages=list(mail.messages(settings.max_emails_per_run));log.info("%s e-mails relevantes encontrados",len(messages))
        for message in messages:
            if any(r.get("status")=="SUCESSO" and message.message_id and r.get("message_id")==message.message_id for r in processed):continue
            safe_id=hashlib.sha256((message.message_id or message.uid).encode()).hexdigest()[:24]
            temp=Path("data/temp")/safe_id;temp.mkdir(parents=True,exist_ok=True)
            try:
                attachments=valid_pdfs(EmailClient.save_pdf_attachments(message,temp))
                if len(attachments)<2:raise ValueError("Menos de dois PDFs válidos; revisão manual necessária")
                hashes={sha256(p) for p in attachments}
                if hashes and hashes.issubset(known_hashes):
                    control.record(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,hash_apolice=next(iter(hashes)),status="IGNORADO",erro="PDFs já processados por hash")
                    continue
                client=_client()
                role_result=client.classify(attachments,[p.name for p in attachments])
                policy,bill=resolve_roles(role_result,attachments)
                policy_analysis=first_pages(policy,temp/"apolice_analise.pdf")
                result=client.analyze(policy_analysis,bill)
                (temp/"resultado.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
                data=validate_policy(result);require_minimum(data)
                if not data.tipo_empresa:raise ValueError("Empresa não identificada com segurança; revisão necessária")
                if dry_run:
                    log.info("DRY RUN: publicaria %s / %s; planilha e estado intactos",data.tipo_empresa,data.nome_pasta)
                    count+=1;continue
                destination,created_files=publish(settings.root_dir,data,policy,bill,return_created=True)
                try:
                    last_excel_error=None
                    for attempt in range(3):
                        try:
                            update_workbook(settings.policies_excel,data,Path("backups"))
                            last_excel_error=None
                            break
                        except PermissionError as excel_error:
                            last_excel_error=excel_error
                            if attempt<2:time.sleep(2**attempt)
                    if last_excel_error:raise last_excel_error
                except Exception:
                    for created_file in created_files:
                        try:created_file.unlink(missing_ok=True)
                        except OSError:log.exception("Falha ao reverter PDF publicado: %s",created_file)
                    raise
                ph,bh=sha256(policy),sha256(bill)
                control.record(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,hash_apolice=ph,hash_boleto=bh,status="SUCESSO",pasta_destino=str(destination))
                known_hashes.update((ph,bh));count+=1
                log.info("Processamento concluído: %s",destination)
                if not settings.keep_success_temp:shutil.rmtree(temp,ignore_errors=True)
            except Exception as exc:
                log.exception("Falha ao processar Message-ID %s",message.message_id or message.uid)
                if not dry_run:
                    try:control.record(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,status="ERRO",erro=str(exc)[:1000])
                    except Exception:log.exception("Não foi possível registrar erro no controle")
    log.info("Execução encerrada; processados nesta rodada=%s",count)
    return 0

def main()->int:
    parser=argparse.ArgumentParser(description="Robô local de controle de apólices THI/PHAS")
    parser.add_argument("--test",action="store_true",help="smoke test offline")
    parser.add_argument("--dry-run",action="store_true",help="analisa sem publicar documentos, alterar Excel ou marcar sucesso")
    args=parser.parse_args()
    try:
        if args.test:return _test()
        if args.dry_run and (not settings.email_user or not settings.email_password):
            log.warning("Credenciais IMAP ausentes: executando apenas smoke test offline; preencha .env para simular e-mails reais")
            return _test()
        return run(args.dry_run)
    except Exception as exc:log.exception("Execução interrompida: %s",exc);return 1
if __name__=="__main__":sys.exit(main())
