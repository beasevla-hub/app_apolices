from datetime import date
from pathlib import Path
import pytest
from app.models import PolicyData
from app.file_manager import sanitize_filename,sha256,build_destination,build_document_names,publish

def policy():return PolicyData(empresa_normalizada='THI',orgao='Órgão',orgao_normalizado='ORGAO',numero_concorrencia_normalizado='01-2026',vigencia_data_inicial=date(2026,8,1),vigencia_data_final=date(2027,8,1),confianca_geral=.9)
def test_deterministic_paths_names_hash_and_sanitization(tmp_path):
    d=policy();assert build_destination(tmp_path,d)==build_destination(tmp_path,d)
    assert build_document_names(d)==build_document_names(d)
    assert sanitize_filename('a/b')=='a-b'
    f=tmp_path/'doc.pdf';f.write_bytes(b'abc');assert len(sha256(f))==64

def test_publish_identical_pdf_idempotent_and_conflict(tmp_path):
    p=tmp_path/'p.pdf';b=tmp_path/'b.pdf';p.write_bytes(b'policy');b.write_bytes(b'bill')
    first,created=publish(tmp_path/'root',policy(),p,b,return_created=True);assert len(created)==2
    _,created=publish(tmp_path/'root',policy(),p,b,return_created=True);assert not created
    (first/'08. BOLETO - ORGAO - 01-2026.pdf').write_bytes(b'other')
    with pytest.raises(FileExistsError):publish(tmp_path/'root',policy(),p,b)
