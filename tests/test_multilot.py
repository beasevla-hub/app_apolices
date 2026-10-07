from pathlib import Path
from app.attachment_processor import resolve_groups

def pdf_names(count):return [Path(f'file_{idx:02d}.pdf') for idx in range(1,count+1)]
def ev(value,confidence=.98):return {'valor':value,'fonte':'APOLICE' if value is not None else 'NAO_IDENTIFICADO','confianca':confidence}
def group(lot,policy,bill,confidence=.98):return {'lote':ev(lot,confidence),'apolice':policy,'boleto':bill}
def test_single_pair_and_unknown_lot():
    files=pdf_names(2);groups,issues=resolve_groups({'grupos':[group(None,files[0].name,files[1].name)],'outros':[],'observacoes':None},files)
    assert len(groups)==1 and groups[0].lote is None and groups[0].problema is None and not issues

def test_two_lots_are_associated_by_filename_not_attachment_order_and_other_is_allowed():
    files=[Path(n) for n in ('policy_03.pdf','bill_01.pdf','extra.pdf','policy_01.pdf','bill_03.pdf')]
    result={'grupos':[group('01','policy_01.pdf','bill_01.pdf'),group('03','policy_03.pdf','bill_03.pdf')],'outros':['extra.pdf'],'observacoes':None}
    groups,issues=resolve_groups(result,files)
    assert [(g.lote,g.apolice.name,g.boleto.name) for g in groups]==[('01','policy_01.pdf','bill_01.pdf'),('03','policy_03.pdf','bill_03.pdf')]
    assert all(g.problema is None for g in groups) and not issues

def test_ten_groups_all_classified_exactly_once():
    files=[Path(f'{kind}_{i:02d}.pdf') for i in range(1,11) for kind in ('apolice','boleto')]
    # Shuffle semantic file order without relying on attachment order.
    files=files[::2]+files[1::2][::-1]
    result={'grupos':[group(f'{i:02d}',f'apolice_{i:02d}.pdf',f'boleto_{i:02d}.pdf') for i in range(1,11)],'outros':[],'observacoes':None}
    groups,issues=resolve_groups(result,files)
    assert len(groups)==10 and not issues
    assert all(g.apolice.name.split('_')[1]==g.boleto.name.split('_')[1] for g in groups)

def test_incomplete_or_shared_pair_is_reviewed_without_invalidating_other_groups():
    files=[Path(n) for n in ('p01.pdf','b01.pdf','p02.pdf','b02.pdf')]
    result={'grupos':[group('01','p01.pdf','b01.pdf'),group('02','p02.pdf',None),group('03','p01.pdf','b02.pdf')],'outros':[],'observacoes':None}
    groups,issues=resolve_groups(result,files)
    assert groups[0].problema is not None and groups[1].problema is not None and groups[2].problema is not None
    assert issues

def test_low_confidence_duplicate_lots_and_unclassified_files_require_review():
    files=[Path(n) for n in ('p1.pdf','b1.pdf','p2.pdf','b2.pdf','unknown.pdf')]
    result={'grupos':[group('01','p1.pdf','b1.pdf',.4),group('01','p2.pdf','b2.pdf')],'outros':[],'observacoes':None}
    groups,issues=resolve_groups(result,files)
    assert all(g.problema for g in groups)
    assert any('não foi classificado' in issue for issue in issues)
