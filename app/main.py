"""Orquestração de e-mails; cada par documental é independente e retomável."""
import argparse,hashlib,json,shutil,sys,time
from pathlib import Path
from datetime import datetime,date,timezone
from .config import settings
from .logger import get_logger
from .email_client import EmailClient,MailMessage,IMAPConnectionLost
from .attachment_processor import valid_pdfs,resolve_groups,DocumentGroup
from .pdf_processor import first_pages
from .openrouter_client import OpenRouterClient
from .validator import validate_policy,require_minimum
from .file_manager import sha256,publish,lot_label
from .excel_robot_control import RobotControl
from .excel_apolices import update_workbook
log=get_logger()
class CountingOpenRouter:
    """Contabiliza chamadas lógicas efetivamente feitas no lote."""
    def __init__(self,client):self.client=client;self.classifications=0;self.analyses=0
    @property
    def calls(self):return self.classifications+self.analyses
    def classify(self,*args,**kwargs):self.classifications+=1;return self.client.classify(*args,**kwargs)
    def analyze(self,*args,**kwargs):self.analyses+=1;return self.client.analyze(*args,**kwargs)
def _client():
    names=[name.strip() for name in (settings.thi_names,settings.phas_names) if name.strip()]
    return OpenRouterClient(settings.openrouter_api_key,settings.openrouter_model,settings.openrouter_base_url,settings.openrouter_timeout,names)
def _write_json(path:Path,value)->None:
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8");temp.replace(path)
def _hash_key(value:str)->str:return hashlib.sha256(value.encode()).hexdigest()
def _group_key(group:DocumentGroup,index:int)->str:
    if group.apolice and group.boleto:
        pair="|".join((group.lote or "",group.apolice.name,sha256(group.apolice),group.boleto.name,sha256(group.boleto)))
        return "PAIR-"+_hash_key(pair)[:24]
    basis=f"{index}|{group.lote or ''}|{group.apolice.name if group.apolice else ''}|{group.boleto.name if group.boleto else ''}"
    return "REVIEW-"+_hash_key(basis)[:20]
def _lot_equal(first:str,second:str)->bool:
    def normalize(value):
        text=" ".join(str(value).casefold().split())
        return text[5:].strip() if text.startswith("lote ") else text
    return normalize(first)==normalize(second)
def _test()->int:
    """Smoke test offline: não acessa e-mail nem serviços externos."""
    from .models import PolicyData,Evidence
    evidence={name:Evidence(valor=value,fonte="APOLICE",confianca=.95) for name,value in {
        "empresa_normalizada":"THI","orgao":"Órgão teste","numero_concorrencia_normalizado":"1-2026",
        "vigencia_data_inicial":date(2026,1,1),"vigencia_data_final":date(2026,12,31)}.items()}
    data=PolicyData(empresa_normalizada="THI",orgao="Órgão teste",numero_concorrencia_normalizado="1-2026",vigencia_data_inicial=date(2026,1,1),vigencia_data_final=date(2026,12,31),par_coerente=True,confianca_geral=.95,evidencias=evidence)
    require_minimum(data);log.info("Smoke test local concluído; validação estrutural e de confiança OK");return 0

def process_message(message:MailMessage,control:RobotControl,client=None,dry_run:bool=False,root_dir:Path|None=None,policies_excel:Path|None=None,backup_dir:Path|None=None,temp_root:Path|None=None,history_root:Path|None=None,mode:str|None=None)->str:
    """Classifica uma vez; analisa/publica cada par independentemente."""
    client=client or _client();root_dir=root_dir or settings.root_dir;policies_excel=policies_excel or settings.policies_excel
    backup_dir=backup_dir or Path("backups");temp_root=temp_root or Path("data/temp");history_root=history_root or Path("data/historico")
    ident=hashlib.sha256((message.message_id or message.uid).encode()).hexdigest()[:24]
    if not control.can_retry(message.message_id,message.uid):
        log.warning("[%s] Limite de tentativas do e-mail atingido; revisão manual",ident);return "IGNORADO"
    attempt=control.attempts(message.message_id,message.uid)+1
    process_id=control.begin(message_id=message.message_id,uid=message.uid,data_email=message.date,remetente=message.sender,assunto=message.subject,modelo_ia=settings.openrouter_model)
    run_mode=mode or ("DRY_RUN" if dry_run else "NORMAL")
    if dry_run and run_mode=="BACKFILL":run_mode="BACKFILL_DRY_RUN"
    temp=temp_root/ident/process_id;history=history_root/process_id;temp.mkdir(parents=True,exist_ok=True);history.mkdir(parents=True,exist_ok=True)
    results=[];classification_calls=0;analysis_calls=0;cache_hit=False
    metadata={"id_processamento":process_id,"message_id":message.message_id,"uid":message.uid,"data_email":message.date,"remetente":message.sender,"assunto":message.subject,"modelo":settings.openrouter_model,"timestamp_utc":datetime.now(timezone.utc).isoformat(),"modo_execucao":run_mode,"quantidade_pdfs":0,"quantidade_grupos":0,"quantidade_lotes":0,"lotes":[],"issues":[],"observacoes_classificacao":None,"chamadas_openrouter":{"classificacao":0,"analises":0,"total":0},"classificacao_cache_reutilizada":False}
    try:
        attachments=valid_pdfs(EmailClient.save_pdf_attachments(message,temp));metadata["quantidade_pdfs"]=len(attachments)
        if len(attachments)<2:raise ValueError("Menos de dois PDFs válidos; revisão manual necessária")
        hashes_by_name={path.name:sha256(path) for path in attachments}
        if control.all_attachments_processed(list(hashes_by_name.values())):
            reason="Todos os PDFs correspondem a pares com hashes já processados com sucesso"
            metadata.update(status="IGNORADO",motivo_idempotencia=reason,quantidade_grupos=None,quantidade_lotes=None)
            control.record(message_id=message.message_id,uid=message.uid,status="IGNORADO",erro=reason,modelo_ia=settings.openrouter_model,id_processamento=process_id)
            _write_json(history/"metadata.json",metadata);_write_json(history/"resultado.json",{"grupos":[],"motivo_idempotencia":reason})
            return "IGNORADO"
        cache_path=history_root/"classificacoes"/(ident+".json");classification=None
        try:
            cached=json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("arquivos_sha256")==hashes_by_name:classification=cached.get("resultado");cache_hit=classification is not None
        except (OSError,ValueError,AttributeError):pass
        if classification is None:
            classification_calls=1;metadata["chamadas_openrouter"]={"classificacao":classification_calls,"analises":analysis_calls,"total":classification_calls+analysis_calls}
            classification=client.classify(attachments,[path.name for path in attachments])
            _write_json(cache_path,{"message_id":message.message_id,"uid":message.uid,"arquivos_sha256":hashes_by_name,"resultado":classification})
        groups,issues=resolve_groups(classification,attachments)
        metadata["quantidade_grupos"]=len(groups);metadata["quantidade_lotes"]=len(groups);metadata["issues"]=issues;metadata["observacoes_classificacao"]=classification.get("observacoes")
        metadata["lotes"]=[{"lote":group.lote,"apolice":group.apolice.name if group.apolice else None,"boleto":group.boleto.name if group.boleto else None,"status":"PENDENTE"} for group in groups]
        metadata["classificacao_cache_reutilizada"]=cache_hit
        multiple_lots=len(groups)>1
        _write_json(history/"metadata.json",metadata)
        for index,group in enumerate(groups,1):
            detail=metadata["lotes"][index-1];group_key=_group_key(group,index);detail["group_key"]=group_key
            if group.problema:
                detail.update(status="ERRO",erro=group.problema)
                if control.can_retry(message.message_id,message.uid,group_key):
                    issue_process=control.begin(message_id=message.message_id,uid=message.uid,group_key=group_key,lote=group.lote,modelo_ia=settings.openrouter_model)
                    control.record(message_id=message.message_id,uid=message.uid,group_key=group_key,lote=group.lote,status="ERRO",erro=group.problema,modelo_ia=settings.openrouter_model,id_processamento=issue_process)
                else:detail["erro"]="Limite de tentativas do grupo atingido; revisão manual"
                continue
            policy,bill=group.apolice,group.boleto;policy_hash,bill_hash=sha256(policy),sha256(bill)
            detail["hash_apolice"]=policy_hash;detail["hash_boleto"]=bill_hash
            previous=control.find(message.message_id,message.uid,group_key)
            if previous and previous.get("status")=="SUCESSO" and previous.get("hash_apolice")==policy_hash and previous.get("hash_boleto")==bill_hash:
                detail.update(status="SUCESSO",id_processamento_anterior=previous.get("id_processamento"),observacao="Par já processado; sem nova chamada OpenRouter")
                continue
            if control.already_processed("",{policy_hash,bill_hash},lot=group.lote):
                earlier=next((row for row in control.rows() if row.get("status")=="SUCESSO" and row.get("hash_apolice")==policy_hash and row.get("hash_boleto")==bill_hash and (group.lote is None or (row.get("lote") or None)==group.lote)),None)
                reused_lot=group.lote if group.lote is not None else (earlier.get("lote") if earlier else None)
                control.record(message_id=message.message_id,uid=message.uid,group_key=group_key,lote=reused_lot,hash_apolice=policy_hash,hash_boleto=bill_hash,status="SUCESSO",erro=None,modelo_ia=settings.openrouter_model,id_processamento=earlier.get("id_processamento") if earlier else process_id)
                detail.update(status="SUCESSO",lote=reused_lot,lote_associado=group.lote,id_processamento_anterior=earlier.get("id_processamento") if earlier else None,observacao="Par já processado em outra mensagem; sem chamada OpenRouter")
                continue
            if not control.can_retry(message.message_id,message.uid,group_key):
                detail.update(status="ERRO",erro="Limite de tentativas do grupo atingido; revisão manual")
                issues.append(f"Grupo {group_key}: limite de tentativas atingido")
                continue
            group_process=control.begin(message_id=message.message_id,uid=message.uid,group_key=group_key,lote=group.lote,hash_apolice=policy_hash,hash_boleto=bill_hash,data_email=message.date,remetente=message.sender,assunto=message.subject,modelo_ia=settings.openrouter_model)
            detail.update(status="PROCESSANDO",id_processamento=group_process)
            metadata["chamadas_openrouter"]={"classificacao":classification_calls,"analises":analysis_calls,"total":classification_calls+analysis_calls}
            _write_json(history/"metadata.json",metadata)
            created=[];destination=None;operational_lot=group.lote
            try:
                policy_analysis=first_pages(policy,temp/(policy.stem+"_analise.pdf"))
                analysis_calls+=1
                metadata["chamadas_openrouter"]={"classificacao":classification_calls,"analises":analysis_calls,"total":classification_calls+analysis_calls}
                if group.lote is None:raw_result=client.analyze(policy_analysis,bill)
                else:raw_result=client.analyze(policy_analysis,bill,expected_lot=group.lote)
                lot_result_path=history/"lotes"/group_key/"resultado.json";_write_json(lot_result_path,raw_result)
                data=validate_policy(raw_result,lote_associado=group.lote)
                if group.lote is not None and data.lote is not None and not _lot_equal(group.lote,data.lote):
                    raise ValueError(f"Lote da análise ({data.lote!r}) não confirma associação classificada ({group.lote!r})")
                require_minimum(data,lote_associado=group.lote)
                if data.lote is not None and "lote" not in data.evidencias:raise ValueError("Extração retornou lote sem evidência; revisão manual")
                operational_lot=data.lote_operacional
                group_label=lot_label(operational_lot, f"GRUPO {index:02d}") if multiple_lots else None
                detail.update(lote=operational_lot,lote_associado=group.lote,lote_documental=data.lote,grupo_pasta=group_label,resultado="lotes/"+group_key+"/resultado.json")
                if dry_run:
                    from .file_manager import build_destination,build_document_names
                    detail.update(status="DRY_RUN",destino_previsto=str(build_destination(root_dir,data,multiple_lots,group_label)),nomes_previstos=list(build_document_names(data,multiple_lots,group_label)))
                    control.record(message_id=message.message_id,uid=message.uid,group_key=group_key,lote=operational_lot,hash_apolice=policy_hash,hash_boleto=bill_hash,status="IGNORADO",erro="DRY_RUN: lote analisado sem publicação",modelo_ia=settings.openrouter_model,id_processamento=group_process)
                else:
                    destination,created=publish(root_dir,data,policy,bill,return_created=True,multiple_lots=multiple_lots,group_label=group_label)
                    try:update_workbook(policies_excel,data,backup_dir)
                    except Exception:
                        for target in created:
                            try:target.unlink(missing_ok=True)
                            except OSError:log.exception("[%s] Rollback do grupo %s falhou",process_id,group_key)
                        raise
                    control.record(message_id=message.message_id,uid=message.uid,group_key=group_key,lote=operational_lot,hash_apolice=policy_hash,hash_boleto=bill_hash,status="SUCESSO",modelo_ia=settings.openrouter_model,pasta_destino=str(destination),id_processamento=group_process)
                    detail.update(status="SUCESSO",destino=str(destination),id_processamento=group_process)
            except Exception as exc:
                log.exception("[%s] Grupo %s falhou; os demais grupos continuarão",process_id,group_key)
                control.record(message_id=message.message_id,uid=message.uid,group_key=group_key,lote=operational_lot,hash_apolice=policy_hash,hash_boleto=bill_hash,status="ERRO",erro=str(exc)[:1000],modelo_ia=settings.openrouter_model,id_processamento=group_process,pasta_destino=str(destination) if destination else None)
                detail.update(status="ERRO",erro=str(exc)[:1000]);issues.append(f"Grupo {group_key}: {exc}")
            results.append(dict(detail))
        if issues:metadata["issues"]=issues
        statuses=[item.get("status") for item in metadata["lotes"]]
        valid_statuses={"SUCESSO"}
        if dry_run and statuses and all(status in {"DRY_RUN","SUCESSO"} for status in statuses):
            overall="IGNORADO";error="DRY_RUN: análise concluída sem publicação"
        elif statuses and all(status in valid_statuses for status in statuses) and not issues:
            overall="SUCESSO";error=None
        elif not groups and not issues:
            overall="IGNORADO";error="Nenhum grupo de documentos relevantes"
        else:
            overall="ERRO";error="; ".join(issues)[:1000] if issues else "Um ou mais grupos exigem revisão"
        control.record(message_id=message.message_id,uid=message.uid,status=overall,erro=error,modelo_ia=settings.openrouter_model,id_processamento=process_id)
        metadata.update(status=overall,quantidade_grupos=len(groups),quantidade_lotes=len(groups),lotes=metadata["lotes"],issues=issues,chamadas_openrouter={"classificacao":classification_calls,"analises":analysis_calls,"total":classification_calls+analysis_calls},classificacao_cache_reutilizada=cache_hit)
        _write_json(history/"metadata.json",metadata);_write_json(history/"resultado.json",{"grupos":metadata["lotes"],"issues":issues})
        if overall=="SUCESSO" and not settings.keep_success_temp:shutil.rmtree(temp,ignore_errors=True)
        return "DRY_RUN" if dry_run and overall=="IGNORADO" else overall
    except Exception as exc:
        log.exception("[%s] Falha no processamento do e-mail: %s",process_id,exc)
        metadata.update(status="ERRO",erro=str(exc)[:1000],chamadas_openrouter={"classificacao":classification_calls,"analises":analysis_calls,"total":classification_calls+analysis_calls},classificacao_cache_reutilizada=cache_hit);_write_json(history/"metadata.json",metadata);_write_json(history/"resultado.json",{"grupos":metadata["lotes"],"erro":str(exc)[:1000]})
        try:control.record(message_id=message.message_id,uid=message.uid,status="ERRO",erro=str(exc)[:1000],modelo_ia=settings.openrouter_model,id_processamento=process_id)
        except Exception:log.exception("[%s] Não foi possível persistir o erro do e-mail",process_id)
        return "SEM_PDFS" if metadata.get("quantidade_pdfs",0)<2 else "ERRO"

def run(dry_run:bool=False,backfill_period:tuple[date,date]|None=None)->int:
    dry_run=dry_run or settings.dry_run
    if not settings.email_user or not settings.email_password:raise RuntimeError("Preencha EMAIL_USER e EMAIL_PASSWORD no .env")
    if not settings.allowed_sender_domains:raise RuntimeError("ALLOWED_SENDER_DOMAINS deve conter ao menos um domínio autorizado")
    control=RobotControl(settings.robot_control,settings.robot_max_attempts);start,end=backfill_period if backfill_period else (None,None);mode="BACKFILL" if backfill_period else None
    counts={"SUCESSO":0,"IGNORADO":0,"ERRO":0,"SEM_PDFS":0};client=None;had_relevant=False;found=relevant=0
    with EmailClient(settings.email_host,settings.email_port,settings.email_user,settings.email_password,settings.email_folder,settings.allowed_sender_domains,settings.email_use_ssl) as mail:
        messages=mail.messages_between(start,end) if backfill_period else mail.messages(settings.max_emails_per_run)
        try:
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
        except IMAPConnectionLost as exc:
            found=mail.last_found_count;relevant=mail.last_relevant_count
            print(f"BACKFILL PARCIAL: {exc}\nMensagens candidatas: {found}; remetentes relevantes lidos: {relevant}; resultados persistidos: {counts}")
            raise
        found=mail.last_found_count;relevant=mail.last_relevant_count
    log.info("Busca IMAP: %s mensagens candidatas, %s remetentes relevantes",found,relevant)
    if not had_relevant:
        if backfill_period:print("Nenhum e-mail relevante encontrado no período informado.")
        else:log.info("Nenhum e-mail relevante encontrado")
        return 0
    if backfill_period:
        print("BACKFILL FINALIZADO");print(f"Período: {start:%d/%m/%Y} → {end:%d/%m/%Y} (inclusivo)")
        print(f"E-mails encontrados: {found}\nE-mails relevantes: {relevant}")
        print(f"E-mails com sucesso: {counts['SUCESSO']}\nIgnorados/revisão: {counts['IGNORADO']+counts.get('DRY_RUN',0)}\nCom erro: {counts['ERRO']}\nSem PDFs válidos: {counts['SEM_PDFS']}")
        print(f"Classificações: {client.classifications if client else 0}\nAnálises de apólices: {client.analyses if client else 0}\nTotal de chamadas: {client.calls if client else 0}\nHistórico: data/historico/")
    else:log.info("Execução encerrada: %s; classificações=%s análises=%s",counts,client.classifications if client else 0,client.analyses if client else 0)
    return 0

def parse_backfill_date(value:str)->date:
    try:return datetime.strptime(value,"%d/%m/%Y").date()
    except ValueError as exc:raise argparse.ArgumentTypeError("Data inválida; use DD/MM/AAAA") from exc
def main()->int:
    parser=argparse.ArgumentParser(description="Robô local de controle de apólices THI/PHAS")
    parser.add_argument("--test",action="store_true",help="smoke test offline");parser.add_argument("--dry-run",action="store_true",help="analisa e valida sem publicar documentos ou atualizar Excel operacional")
    parser.add_argument("--backfill",action="store_true",help="processa mensagens de um período histórico inclusivo");parser.add_argument("--inicio",type=parse_backfill_date,help="data inicial DD/MM/AAAA");parser.add_argument("--fim",type=parse_backfill_date,help="data final inclusiva DD/MM/AAAA")
    args=parser.parse_args()
    if args.backfill and (args.inicio is None or args.fim is None):parser.error("--backfill exige --inicio e --fim no formato DD/MM/AAAA")
    if not args.backfill and (args.inicio is not None or args.fim is not None):parser.error("--inicio e --fim só podem ser usados com --backfill")
    if args.backfill and args.fim<args.inicio:parser.error("--fim deve ser igual ou posterior a --inicio")
    if args.test and (args.backfill or args.dry_run):parser.error("--test offline não pode ser combinado com --backfill ou --dry-run")
    try:return _test() if args.test else run(args.dry_run,(args.inicio,args.fim) if args.backfill else None)
    except Exception as exc:log.exception("Execução interrompida: %s",exc);return 1
if __name__=="__main__":sys.exit(main())
