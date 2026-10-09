"""Geração determinística e publicação transacional por par documental."""
from pathlib import Path
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from .models import PolicyData

INVALID=re.compile(r'[<>:"/\\|?*\x00-\x1f]')
logger=logging.getLogger("robo_apolices")
SYNC_MARKERS=("onedrive","sharepoint","dropbox","google drive","googledrive","icloud","syncthing","sync.com")
# Mantém margem antes do limite clássico de 260 caracteres do Windows.
MAX_PUBLICATION_PATH_CHARS=240


def sanitize_filename(name:str)->str:
    value=INVALID.sub("-",str(name)).strip(" .")
    return value[:180] or "documento.pdf"


def sha256(path:Path)->str:
    digest=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()


def lot_label(lot:str|None,unknown_group:str|None=None)->str|None:
    if lot is None:return sanitize_filename(unknown_group) if unknown_group else None
    clean=sanitize_filename(" ".join(str(lot).strip().split())).upper()
    return clean if clean.casefold().startswith("lote") else sanitize_filename("LOTE "+clean)


def build_document_names(data:PolicyData,multiple_lots:bool=False,group_label:str|None=None)->tuple[str,str]:
    return "01. APOLICE.pdf","08. BOLETO.pdf"


def _legacy_document_names(data:PolicyData,multiple_lots:bool=False,group_label:str|None=None)->tuple[str,str]:
    """Nomes anteriores, usados só para reconhecer um par já publicado; nunca são criados."""
    org=sanitize_filename(data.orgao_normalizado or data.orgao or "ORGAO")
    number=sanitize_filename(data.numero_concorrencia_normalizado or "CONCORRENCIA-NAO-INFORMADA")
    suffix=lot_label(data.lote_operacional,group_label) if multiple_lots else None
    base=sanitize_filename(f"{org} - {number}"+(f" - {suffix}" if suffix else ""))
    return f"01. APOLICE - {base}.pdf",f"08. BOLETO - {base}.pdf"


def build_destination(root:Path,data:PolicyData,multiple_lots:bool=False,group_label:str|None=None)->Path:
    if not data.minimum_data_present():raise ValueError("Dados mínimos ausentes; documentos não publicados")
    if data.empresa_normalizada not in {"THI","PHAS"}:raise ValueError("empresa_normalizada não identificada")
    folder_date=data.vigencia_data_inicial.strftime("%d.%m.%Y")
    org=sanitize_filename(data.orgao_normalizado or data.orgao or "ORGAO")
    number=sanitize_filename(data.numero_concorrencia_normalizado or "")
    destination=Path(root)/data.empresa_normalizada/folder_date/sanitize_filename(f"{org} - {number}")
    suffix=lot_label(data.lote_operacional,group_label) if multiple_lots else None
    return destination/suffix if suffix else destination


def _absolute(path:Path|None)->str|None:
    if path is None:return None
    return os.path.abspath(os.fspath(path))


def _safe_exists(path:Path|None)->bool|None:
    if path is None:return None
    try:return path.exists()
    except OSError:return False


def _diagnostic(operation:str,source:Path|None,destination:Path|None,temp:Path|None,destination_dir:Path|None,created:list[Path])->str:
    paths={"source":source,"destination":destination,"temporary":temp,"destination_directory":destination_dir}
    absolute={key:_absolute(value) for key,value in paths.items()}
    lengths={key:(len(value) if value is not None else None) for key,value in absolute.items()}
    components={key:(Path(value).parts if value is not None else None) for key,value in absolute.items()}
    component_lengths={key:([len(part) for part in Path(value).parts] if value is not None else None) for key,value in absolute.items()}
    sync_paths=[]
    for key,value in absolute.items():
        if value is None:continue
        matched=[marker for marker in SYNC_MARKERS if marker in value.casefold()]
        if matched:sync_paths.append({"path_kind":key,"markers":matched})
    details={
        "operation":operation,
        "cwd":os.path.abspath(os.getcwd()),
        "absolute_paths":absolute,
        "path_lengths_characters":lengths,
        "path_components":components,
        "path_component_lengths":component_lengths,
        "dangerous_path_limit_characters":MAX_PUBLICATION_PATH_CHARS,
        "paths_over_limit":{key:length for key,length in lengths.items() if length is not None and length>MAX_PUBLICATION_PATH_CHARS},
        "source_exists":_safe_exists(source),
        "source_is_file":(source.is_file() if source is not None and _safe_exists(source) else False if source is not None else None),
        "source_read_access":(os.access(source,os.R_OK) if source is not None else None),
        "destination_directory_exists":_safe_exists(destination_dir),
        "destination_directory_is_dir":(destination_dir.is_dir() if destination_dir is not None and _safe_exists(destination_dir) else False if destination_dir is not None else None),
        "destination_directory_write_access":(os.access(destination_dir,os.W_OK) if destination_dir is not None and _safe_exists(destination_dir) else False if destination_dir is not None else None),
        "destination_exists":_safe_exists(destination),
        "temporary_exists":_safe_exists(temp),
        "created_files_this_attempt":[_absolute(path) for path in created],
        "possible_sync_folder_paths":sync_paths,
    }
    return json.dumps(details,ensure_ascii=False,default=str)


def _annotate(exc:Exception|KeyboardInterrupt|SystemExit,details:str)->None:
    try:exc.add_note("Diagnóstico da publicação: "+details)
    except (AttributeError,TypeError):pass


def _remove(path:Path)->str|None:
    try:path.unlink(missing_ok=True);return None
    except OSError as exc:return f"{_absolute(path)}: {type(exc).__name__}: {exc}"


def publish(root:Path,data:PolicyData,policy:Path,bill:Path,return_created:bool=False,multiple_lots:bool=False,group_label:str|None=None):
    destination=build_destination(root,data,multiple_lots,group_label)
    policy_name,bill_name=build_document_names(data,multiple_lots,group_label)
    pairs=[(Path(policy),destination/policy_name),(Path(bill),destination/bill_name)]
    created=[];temporaries=[];source_hashes={};failed=False;failure_exception=None;operation="validate absolute publication path lengths";active_source,active_destination=pairs[0];active_temp=destination/f".publish-{uuid.uuid4().hex}.tmp"
    try:
        for source,target in pairs:
            active_source,active_destination,active_temp=source,target,destination/f".publish-{uuid.uuid4().hex}.tmp"
            candidate_paths={"source":source,"destination":target,"temporary":active_temp,"destination_directory":destination}
            too_long={kind:len(_absolute(path)) for kind,path in candidate_paths.items() if len(_absolute(path))>MAX_PUBLICATION_PATH_CHARS}
            if too_long:raise OSError(f"Caminho absoluto perigosamente longo; limite preventivo {MAX_PUBLICATION_PATH_CHARS} caracteres; comprimentos excedidos={too_long}")
            operation="validate source PDF"
            if not source.is_file():raise FileNotFoundError(f"PDF de origem não existe ou não é arquivo: {_absolute(source)}")
            operation="hash source PDF"
            source_hash=sha256(source)
            source_hashes[source]=source_hash
        operation="create destination directory"
        destination.mkdir(parents=True,exist_ok=True)
        if not destination.is_dir() or not os.access(destination,os.W_OK):
            raise PermissionError(f"Diretório de destino não existe, não é diretório ou não permite gravação: {_absolute(destination)}")
        targets=[target for _,target in pairs]
        if not any(target.exists() for target in targets):
            legacy_names=_legacy_document_names(data,multiple_lots,group_label)
            legacy_targets=[destination/name for name in legacy_names]
            legacy_paths_safe=all(len(_absolute(path))<=MAX_PUBLICATION_PATH_CHARS for path in legacy_targets)
            operation="check previously published legacy pair"
            if legacy_paths_safe and all(path.is_file() for path in legacy_targets) and all(sha256(path)==source_hashes[source] for (source,_),path in zip(pairs,legacy_targets)):
                logger.info("Par documental idêntico já publicado com os nomes legados; preservando arquivos sem renomear: %s",[ _absolute(path) for path in legacy_targets])
                return (destination,created) if return_created else destination
        for source,target in pairs:
            active_source,active_destination,active_temp=source,target,destination/f".publish-{uuid.uuid4().hex}.tmp"
            operation="check existing destination"
            if target.exists():
                if sha256(target)==source_hashes[source]:continue
                raise FileExistsError(f"Destino existente possui conteúdo diferente: {_absolute(target)}")
            operation="validate source immediately before copy"
            if not source.is_file():raise FileNotFoundError(f"PDF de origem desapareceu antes da cópia: {_absolute(source)}")
            if not destination.is_dir() or not os.access(destination,os.W_OK):
                raise FileNotFoundError(f"Diretório de destino desapareceu ou ficou inacessível antes da cópia: {_absolute(destination)}")
            # Um nome curto e exclusivo evita colisões entre execuções e reduz riscos
            # de sincronizadores disputarem o mesmo arquivo .tmp determinístico.
            temporaries.append(active_temp)
            operation="shutil.copy2 source PDF to temporary file"
            shutil.copy2(source,active_temp)
            operation="verify temporary PDF hash"
            if sha256(active_temp)!=source_hashes[source]:raise OSError(f"Hash do temporário não corresponde à origem: {_absolute(active_temp)}")
            operation="atomically replace temporary PDF with destination"
            os.replace(active_temp,target)
            temporaries.remove(active_temp)
            created.append(target)
            operation="verify published PDF hash"
            if sha256(target)!=source_hashes[source]:raise OSError(f"Hash do PDF publicado não corresponde à origem: {_absolute(target)}")
    except (KeyboardInterrupt,SystemExit) as exc:
        failed=True
        failure_exception=exc
        raise
    except Exception as exc:
        failed=True
        failure_exception=exc
        details=_diagnostic(operation,active_source,active_destination,active_temp,destination,created)
        _annotate(exc,details)
        logger.error("Falha ao publicar PDF; operation=%s; diagnostic=%s; original_exception=%r",operation,details,exc,exc_info=(type(exc),exc,exc.__traceback__))
        raise
    finally:
        cleanup_errors=[]
        for temporary in temporaries:
            error=_remove(temporary)
            if error:cleanup_errors.append(error)
        if failed:
            for target in reversed(created):
                error=_remove(target)
                if error:cleanup_errors.append(error)
        if cleanup_errors:
            note="Falha ao limpar temporários/rollback da publicação: "+"; ".join(cleanup_errors)
            if failure_exception is not None:
                # O traceback original permanece como exceção principal.
                # Se o runtime não suporta add_note, a falha original ainda é propagada.
                try:failure_exception.add_note(note)
                except (AttributeError,TypeError):pass
            logger.error("Falha ao limpar temporários/rollback da publicação: %s",note)
    return (destination,created) if return_created else destination
