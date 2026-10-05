"""Check the actual captured immutable groups without guessing future cohorts."""
from pathlib import Path,PurePosixPath
import hashlib,re


def sha(path):
    path=Path(path)
    assert path.is_absolute() and '..' not in path.parts
    current=Path(path.anchor)
    for part in path.parts[1:]:
        current/=part
        assert not current.is_symlink()
        assert not hasattr(current,'is_junction') or not current.is_junction()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(binding):
    assert binding['schema']=='actual_score_protected_source_groups_v1'
    assert binding['model_calls']==binding['eda_calls']==0
    groups=binding['groups'];assert isinstance(groups,dict) and groups
    count=0
    for identity,group in groups.items():
        assert isinstance(identity,str) and identity
        assert PurePosixPath(group['cloud_root']).is_absolute()
        assert isinstance(group['source_hashes'],dict) and group['source_hashes']
        for name,digest in dict(group['source_hashes'],**{group['spec_name']:group['spec_sha256']}).items():
            path=PurePosixPath(name)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in name
            assert re.fullmatch('[0-9a-f]{64}',digest)
        count+=len(group['source_hashes'])
    assert type(binding['source_assets']) is int and count==binding['source_assets']
    return count


def check(binding,roots=None):
    count=validate(binding);groups={}
    if roots is not None:assert set(roots)==set(binding['groups'])
    for identity,expected in binding['groups'].items():
        root=Path(expected['cloud_root'] if roots is None else roots[identity])
        actual_spec=sha(root/expected['spec_name']);assert actual_spec==expected['spec_sha256'],identity
        actual={n:sha(root/n) for n in expected['source_hashes']}
        assert actual==expected['source_hashes'],identity
        groups[identity]=dict(spec_sha256=actual_spec,source_hashes=actual,source_assets=len(actual))
    return dict(schema='compile_diag_protected_source_check_v1',verified=True,groups=groups,
        source_assets=count,model_calls=0,eda_calls=0)
