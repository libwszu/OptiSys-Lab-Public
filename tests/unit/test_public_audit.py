"""Integrity and disclosure controls for the public audit edition."""
import hashlib,importlib.util,io,json,zipfile
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('public_audit_verifier',ROOT/'scripts/verify_public_audit.py')
verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
def archive(tmp_path,payload=b'ordinary sample',schema=None):
    entry={'path':'sample.txt','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    manifest={'schema':schema or verifier.SCHEMA,'package_id':verifier.PACKAGE_ID,'files':[entry]}
    path=tmp_path/'public.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('sample.txt',payload);z.writestr('manifest.json',json.dumps(manifest))
        z.writestr('SHA256SUMS.txt',entry['sha256']+'  sample.txt\n')
    return path
def mutate(path,transform):
    with zipfile.ZipFile(path) as z:members={n:z.read(n) for n in z.namelist()}
    transform(members)
    with zipfile.ZipFile(path,'w') as z:
        for name,data in members.items():z.writestr(name,data)
def test_valid_public_package(tmp_path):
    assert verifier.verify(archive(tmp_path))['status']=='PASS'
def test_tampered_member_rejected(tmp_path):
    path=archive(tmp_path);mutate(path,lambda m:m.update({'sample.txt':b'changed sample'}))
    assert any('member_hash_mismatch' in x for x in verifier.verify(path)['issues'])
def test_deleted_required_member_rejected(tmp_path):
    path=archive(tmp_path);mutate(path,lambda m:m.pop('sample.txt'))
    assert 'manifest_membership_mismatch' in verifier.verify(path)['issues']
def test_private_path_rejected_even_with_consistent_hashes(tmp_path):
    # Synthetic numeric home name is assembled so the fixture source is public-safe.
    payload=('C:'+chr(92)+'Users'+chr(92)+'987654321'+chr(92)+'secret.txt').encode()
    result=verifier.verify(archive(tmp_path,payload))
    assert not result['issues'] and result['privacy_status']=='FAIL'
def test_marked_placeholders_and_mock_paths_are_allowed(tmp_path):
    payload=b'<USER_PROFILE>/cache <PROJECT_ROOT>/examples /home/fixture_user/data /home/runner/work'
    assert verifier.verify(archive(tmp_path,payload))['status']=='PASS'
def test_nested_archive_privacy_rejected(tmp_path):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('private.txt',('C:'+chr(92)+'Users'+chr(92)+'987654321').encode())
    assert verifier.verify(archive(tmp_path,data.getvalue()))['privacy_status']=='FAIL'
def test_original_schema_cannot_be_certified_as_public_edition(tmp_path):
    assert 'wrong_package_schema_or_id' in verifier.verify(archive(tmp_path,schema='optisys.legacy/1'))['issues']
def test_unsafe_member_rejected(tmp_path):
    path=archive(tmp_path);mutate(path,lambda m:m.update({'../outside.txt':b'unsafe'}))
    assert 'unsafe_member' in verifier.verify(path)['issues']
