"""Read-only verification of the root-captured eight immutable source groups."""
from pathlib import Path
import hashlib


def sha(path):
    path = Path(path)
    assert path.is_absolute() and '..' not in path.parts
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        assert not current.is_symlink()
        assert not hasattr(current, 'is_junction') or not current.is_junction()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(binding, roots=None):
    """roots is an explicit mapping only for local readonly preflight/tests."""
    assert binding['schema']=='actual_guidance_protected_eight_groups_v1'
    assert len(binding['groups'])==8 and binding['source_assets']==232
    assert sum(len(group['source_hashes']) for group in binding['groups'].values())==232
    assert binding['model_calls']==binding['eda_calls']==0
    groups={}
    for identity, expected in binding['groups'].items():
        root=Path(expected['cloud_root'] if roots is None else roots[identity])
        actual_spec=sha(root/expected['spec_name'])
        assert actual_spec==expected['spec_sha256'],identity
        actual={name:sha(root/name) for name in expected['source_hashes']}
        assert actual==expected['source_hashes'],identity
        groups[identity]=dict(spec_sha256=actual_spec,source_hashes=actual,source_assets=len(actual))
    return dict(schema='guidance_protected_source_check_v1',verified=True,groups=groups,
                source_assets=232,model_calls=0,eda_calls=0)
