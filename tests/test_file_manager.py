from datetime import date
from pathlib import Path
import pytest
from app.models import PolicyData
from app.file_manager import sanitize_filename,sha256,build_destination,build_document_names,publish

def policy():return PolicyData(empresa_normalizada='THI',orgao='Órgão',orgao_normalizado='ORGAO',numero_concorrencia_normalizado='01-2026',vigencia_data_inicial=date(2026,8,1),vigencia_data_final=date(2027,8,1),confianca_geral=.9)
def test_deterministic_paths_names_hash_and_sanitization(tmp_path):
    d=policy();assert build_destination(tmp_path,d)==build_destination(tmp_path,d)
    assert build_document_names(d)==("01. APOLICE.pdf","08. BOLETO.pdf")
    assert build_document_names(d,True,"LOTE 02")==("01. APOLICE.pdf","08. BOLETO.pdf")
    lot_destination=build_destination(tmp_path,d,True,"LOTE 02")
    assert lot_destination.name=="LOTE 02" and lot_destination.parent==build_destination(tmp_path,d)
    assert sanitize_filename('a/b')=='a-b'
    f=tmp_path/'doc.pdf';f.write_bytes(b'abc');assert len(sha256(f))==64

def test_publish_identical_pdf_idempotent_and_conflict(tmp_path):
    p=tmp_path/'p.pdf';b=tmp_path/'b.pdf';p.write_bytes(b'policy');b.write_bytes(b'bill')
    first,created=publish(tmp_path/'root',policy(),p,b,return_created=True);assert len(created)==2
    _,created=publish(tmp_path/'root',policy(),p,b,return_created=True);assert not created
    (first/'08. BOLETO.pdf').write_bytes(b'other')
    with pytest.raises(FileExistsError):publish(tmp_path/'root',policy(),p,b)



def _publish_fixture(tmp_path):
    source_policy=tmp_path/'source-policy.pdf';source_bill=tmp_path/'source-bill.pdf'
    source_policy.write_bytes(b'policy-content');source_bill.write_bytes(b'bill-content')
    return source_policy,source_bill


def _published_paths(root,data):
    destination=build_destination(root,data)
    names=build_document_names(data)
    return destination,destination/names[0],destination/names[1]


def test_publish_creates_missing_destination_and_returns_two_published_files(tmp_path):
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path);root=tmp_path/'not-created-yet'/'nested'
    destination=build_destination(root,data)
    assert not destination.exists()
    result,created=publish(root,data,source_policy,source_bill,return_created=True)
    assert result==destination and destination.is_dir() and len(created)==2
    assert all(path.is_file() for path in created)
    assert not list(destination.glob('*.tmp'))


def test_publish_missing_source_reports_absolute_paths_and_original_error(tmp_path,monkeypatch,caplog):
    import app.file_manager as manager
    data=policy();source_policy=tmp_path/'missing-policy.pdf';source_bill=tmp_path/'source-bill.pdf';source_bill.write_bytes(b'bill')
    root=tmp_path/'OneDrive - synced'
    monkeypatch.setattr(manager.shutil,'copy2',lambda *args,**kwargs:pytest.fail('copy2 não deve rodar com origem ausente'))
    with pytest.raises(FileNotFoundError) as caught:
        publish(root,data,source_policy,source_bill)
    diagnostic=' '.join(getattr(caught.value,'__notes__',[]))
    assert str(source_policy.resolve()) in diagnostic and 'path_lengths_characters' in diagnostic and 'path_component_lengths' in diagnostic
    assert 'possible_sync_folder_paths' in diagnostic and 'source_exists' in caplog.text
    assert 'FileNotFoundError' in caplog.text and str(build_destination(root,data)) in caplog.text
    destination=build_destination(root,data)
    assert not list(destination.glob('*.tmp')) and not list(destination.glob('*.pdf'))


def test_publish_rejects_destination_without_write_access(tmp_path,monkeypatch,caplog):
    import app.file_manager as manager
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path);root=tmp_path/'docs'
    destination=build_destination(root,data);destination.mkdir(parents=True)
    real_access=manager.os.access
    monkeypatch.setattr(manager.os,'access',lambda path,mode:False if Path(path)==destination else real_access(path,mode))
    with pytest.raises(PermissionError,match='não permite gravação') as caught:
        publish(root,data,source_policy,source_bill)
    diagnostic=' '.join(getattr(caught.value,'__notes__',[]))
    assert 'destination_directory_write_access' in diagnostic
    assert str(destination.resolve()) in caplog.text
    assert not list(destination.glob('*.pdf')) and not list(destination.glob('*.tmp'))


def test_publish_copy_failure_on_second_pdf_rolls_back_first_and_removes_tmp(tmp_path,monkeypatch,caplog):
    import app.file_manager as manager
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path);root=tmp_path/'docs'
    original_copy=manager.shutil.copy2
    def fail_second(source,target):
        assert Path(source).is_file()
        assert Path(target).parent.is_dir()
        if Path(source)==source_bill:
            Path(target).write_bytes(b'partial second copy')
            raise FileNotFoundError(3,'simulated WinError 3 during copy')
        return original_copy(source,target)
    monkeypatch.setattr(manager.shutil,'copy2',fail_second)
    with pytest.raises(FileNotFoundError,match='simulated WinError 3') as caught:
        publish(root,data,source_policy,source_bill)
    destination,policy_target,bill_target=_published_paths(root,data)
    assert not policy_target.exists() and not bill_target.exists()
    assert not list(destination.glob('*.tmp'))
    assert 'shutil.copy2 source PDF to temporary file' in caplog.text
    assert str(source_bill.resolve()) in caplog.text and str(bill_target.resolve()) in caplog.text
    assert any('possible_sync_folder_paths' in note for note in caught.value.__notes__)


def test_publish_existing_same_hash_is_idempotent_and_preserves_pair(tmp_path):
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path);root=tmp_path/'docs'
    destination,created=publish(root,data,source_policy,source_bill,return_created=True)
    assert len(created)==2
    second_destination,created_again=publish(root,data,source_policy,source_bill,return_created=True)
    assert second_destination==destination and created_again==[]
    assert sha256(_published_paths(root,data)[1])==sha256(source_policy)
    assert sha256(_published_paths(root,data)[2])==sha256(source_bill)


def test_publish_different_existing_content_conflict_rolls_back_new_first_pdf(tmp_path):
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path);root=tmp_path/'docs'
    destination,policy_target,bill_target=_published_paths(root,data);destination.mkdir(parents=True)
    bill_target.write_bytes(b'pre-existing other content')
    with pytest.raises(FileExistsError,match='conteúdo diferente') as caught:
        publish(root,data,source_policy,source_bill)
    assert not policy_target.exists() and bill_target.read_bytes()==b'pre-existing other content'
    assert 'check existing destination' in ' '.join(caught.value.__notes__)
    assert not list(destination.glob('*.tmp'))


def test_publish_os_replace_failure_on_second_pdf_rolls_back_pair_and_tmp(tmp_path,monkeypatch):
    import app.file_manager as manager
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path);root=tmp_path/'docs'
    original_replace=manager.os.replace
    def fail_second_replace(source,target):
        if Path(target).name.startswith('08. BOLETO'):
            raise OSError('simulated atomic replace failure')
        return original_replace(source,target)
    monkeypatch.setattr(manager.os,'replace',fail_second_replace)
    with pytest.raises(OSError,match='simulated atomic replace failure'):
        publish(root,data,source_policy,source_bill)
    destination,policy_target,bill_target=_published_paths(root,data)
    assert not policy_target.exists() and not bill_target.exists()
    assert not list(destination.glob('*.tmp'))


def test_publish_rejects_dangerously_long_paths_before_copy_or_replace(tmp_path,monkeypatch,caplog):
    import app.file_manager as manager
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path)
    root=tmp_path/('r'*80)/('s'*80)
    monkeypatch.setattr(manager.shutil,'copy2',lambda *args,**kwargs:pytest.fail('não deve copiar caminho longo'))
    monkeypatch.setattr(manager.os,'replace',lambda *args,**kwargs:pytest.fail('não deve chamar os.replace para caminho longo'))
    with pytest.raises(OSError,match='Caminho absoluto perigosamente longo') as caught:
        publish(root,data,source_policy,source_bill)
    diagnostic=' '.join(getattr(caught.value,'__notes__',[]))
    assert 'dangerous_path_limit_characters' in diagnostic and 'paths_over_limit' in diagnostic
    assert 'validate absolute publication path lengths' in caplog.text
    assert not root.exists()


@pytest.mark.parametrize(('multiple_lots','group_label','legacy_suffix'),[(False,None,''),(True,'LOTE 02',' - LOTE 02')])
def test_publish_recognizes_old_named_pair_without_renaming_or_deleting(tmp_path,multiple_lots,group_label,legacy_suffix):
    data=policy();source_policy,source_bill=_publish_fixture(tmp_path);root=tmp_path/'docs'
    destination=build_destination(root,data,multiple_lots,group_label);destination.mkdir(parents=True)
    old_base=f'ORGAO - 01-2026{legacy_suffix}'
    old_policy=destination/f'01. APOLICE - {old_base}.pdf'
    old_bill=destination/f'08. BOLETO - {old_base}.pdf'
    old_policy.write_bytes(source_policy.read_bytes());old_bill.write_bytes(source_bill.read_bytes())
    result,created=publish(root,data,source_policy,source_bill,return_created=True,multiple_lots=multiple_lots,group_label=group_label)
    assert result==destination and created==[]
    assert old_policy.exists() and old_bill.exists()
    assert not (destination/'01. APOLICE.pdf').exists() and not (destination/'08. BOLETO.pdf').exists()
