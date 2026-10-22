"""Verify the explicitly redacted R2 audit package, never the historical original.

Uses the Python standard library. SHA/CRC validation establishes integrity against
the supplied manifest; use the separately supplied archive SHA for authenticity.
"""
from __future__ import annotations
import argparse,ast,hashlib,io,json,re,stat,struct,zipfile
from pathlib import Path,PurePosixPath

SCHEMA='optisys.public_redacted_audit/2'
PACKAGE_ID='OptiSysLab_S6R_PUBLIC_REDACTED_R2'
HOME=re.compile(rb'(?i)(?:[A-Z]:[\\/]+Users[\\/]+([^\\/\s"<>]+)|/home/([^/\s"<>]+)|/Users/([^/\s"<>]+))')
PHONE=re.compile(rb'\b1[3-9][0-9]{9}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
WORKSPACE=re.compile(rb'(?i)E:[\\/]+optisys\b')
REVISIONS=re.compile(rb'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])')
PUBLIC_USERS={b'runner',b'runneradmin',b'vssadministrator',b'fixture_user',b'example',b'testuser',b'alice'}
SECRETS=[re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|AKIA[A-Z0-9]{16})\b')]
def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def safe_name(name:str)->bool:
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and '\x00' not in name and not re.match(r'^[A-Za-z]:',name) and str(p)==name
def privacy(data:bytes,name:str,depth:int=0)->list[dict]:
    issues=[]
    if depth>5:return [{'path':name,'kind':'archive_depth_exceeded'}]
    if data.startswith(b'PK\x03\x04'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos=z.infolist()
                if len(infos)>10000 or sum(i.file_size for i in infos)>200_000_000:
                    return [{'path':name,'kind':'archive_budget_exceeded'}]
                for i in infos:
                    if i.is_dir():continue
                    if not safe_name(i.filename) or stat.S_ISLNK(i.external_attr>>16) or i.flag_bits&1:
                        issues.append({'path':name,'kind':'unsafe_nested_member'});continue
                    issues+=privacy(z.read(i),name+'!'+i.filename,depth+1)
        except (zipfile.BadZipFile,RuntimeError):issues.append({'path':name,'kind':'invalid_nested_zip'})
        return issues
    if data.startswith(b'\x93NUMPY'):
        try:
            major=data[6];offset=10 if major==1 else 12
            size=int.from_bytes(data[8:offset],'little')
            header=ast.literal_eval(data[offset:offset+size].decode('latin1'))
            descr=str(header['descr'])
            if 'O' in descr:issues.append({'path':name,'kind':'object_array_disallowed'})
            if not any(c in descr for c in ['O','S','U']):return issues
        except (KeyError,ValueError,SyntaxError,IndexError):return [{'path':name,'kind':'invalid_npy_header'}]
    if data.startswith(b'\x89PNG'):
        # Scan textual PNG chunks, not compressed raster noise.
        offset=8;text=[]
        while offset+12<=len(data):
            size=int.from_bytes(data[offset:offset+4],'big');kind=data[offset+4:offset+8]
            if kind in [b'tEXt',b'iTXt',b'eXIf']:text.append(data[offset+8:offset+8+size])
            if kind==b'zTXt':issues.append({'path':name,'kind':'compressed_png_text_requires_review'})
            offset+=size+12
        data=b'\n'.join(text)
    for rx in SECRETS:
        for m in rx.finditer(data):issues.append({'path':name,'kind':'credential_pattern','fingerprint':sha(m.group())})
    for rx,kind in [(PHONE,'phone_format_email'),(WORKSPACE,'private_workspace_prefix'),(REVISIONS,'legacy_git_revision')]:
        for m in rx.finditer(data):issues.append({'path':name,'kind':kind,'fingerprint':sha(m.group())})
    for m in HOME.finditer(data):
        user=next(x for x in m.groups() if x is not None).lower()
        if user not in PUBLIC_USERS and not user.startswith((b'[',b'(')):
            issues.append({'path':name,'kind':'personal_home_path','fingerprint':sha(m.group())})
    return issues
def verify(path:Path,expected_sha256:str|None=None)->dict:
    issues=[];privacy_issues=[];checked=0;package_id=None
    data=path.read_bytes();digest=sha(data)
    if expected_sha256 and expected_sha256!=digest:issues.append('archive_sha256_mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if len(names)!=len(set(names)):issues.append('duplicate_members')
            if len(infos)>10000 or sum(i.file_size for i in infos)>200_000_000:issues.append('archive_budget_exceeded')
            for i in infos:
                if i.is_dir() or not safe_name(i.filename) or stat.S_ISLNK(i.external_attr>>16) or i.flag_bits&1:issues.append('unsafe_member')
            if issues:return {'schema':'optisys.public_audit_verification/2','status':'FAIL','issues':issues,'privacy_issues':[],'sha256':digest}
            if z.testzip() is not None:issues.append('zip_crc_failure')
            manifest=json.loads(z.read('manifest.json'));package_id=manifest.get('package_id')
            if manifest.get('schema')!=SCHEMA or package_id!=PACKAGE_ID:issues.append('wrong_package_schema_or_id')
            entries=manifest.get('files',[]);lookup={i['path']:i for i in entries}
            if len(lookup)!=len(entries):issues.append('duplicate_manifest_paths')
            actual=set(names)-{'manifest.json','SHA256SUMS.txt'}
            if set(lookup)!=actual:issues.append('manifest_membership_mismatch')
            sums={}
            for line in z.read('SHA256SUMS.txt').decode().splitlines():
                h,sep,n=line.partition('  ')
                if not sep or n in sums or not re.fullmatch(r'[0-9a-f]{64}',h):issues.append('invalid_checksum_record')
                sums[n]=h
            if set(sums)!=set(lookup):issues.append('checksum_membership_mismatch')
            for n,item in lookup.items():
                if not safe_name(n) or n not in actual:continue
                payload=z.read(n);checked+=1
                if len(payload)!=item['bytes'] or sha(payload)!=item['sha256'] or sums.get(n)!=item['sha256']:issues.append('member_hash_mismatch:'+n)
            for n in names:privacy_issues+=privacy(z.read(n),n)
    except (zipfile.BadZipFile,KeyError,ValueError,UnicodeError,RuntimeError) as e:
        issues.append('invalid_package:'+type(e).__name__)
    return {'schema':'optisys.public_audit_verification/2','status':'PASS' if not issues and not privacy_issues else 'FAIL','package_id':package_id,'sha256':digest,'members_checked':checked,'issues':issues,'privacy_issues':privacy_issues,'privacy_status':'PASS' if not privacy_issues else 'FAIL'}
def main()->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);parser.add_argument('--expected-sha256');parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=verify(args.archive,args.expected_sha256);text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text,encoding='utf-8')
    print(text,end='');return 0 if result['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
