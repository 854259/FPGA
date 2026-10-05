"""Readonly root-captured source groups; counts come from actual binding data."""
from pathlib import Path
import hashlib

def sha(path):
    path=Path(path);assert path.is_absolute() and '..' not in path.parts
    current=Path(path.anchor)
    for part in path.parts[1:]:
        current/=part;assert not current.is_symlink()
        assert not hasattr(current,'is_junction') or not current.is_junction()
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(binding,roots=None):
    assert isinstance(binding['schema'],str) and binding['schema'].startswith('actual_')
    assert len(binding['groups'])>=8
    assert binding['source_assets']==sum(len(value['source_hashes']) for value in binding['groups'].values())
    assert binding['model_calls']==binding['eda_calls']==0
    groups={}
    for identity,item in binding['groups'].items():
        root=Path(item['cloud_root'] if roots is None else roots[identity])
        spec=sha(root/item['spec_name']);assert spec==item['spec_sha256'],identity
        sources={name:sha(root/name) for name in item['source_hashes']};assert sources==item['source_hashes'],identity
        groups[identity]=dict(spec_sha256=spec,source_hashes=sources,source_assets=len(sources))
    return dict(schema='semantic_edge_protected_source_check_v1',verified=True,groups=groups,
                source_assets=binding['source_assets'],model_calls=0,eda_calls=0)
