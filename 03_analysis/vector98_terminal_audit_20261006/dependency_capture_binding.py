"""Bind an inherited dependency capture through its frozen parent and archive bytes."""
from pathlib import PurePosixPath


def verify(run, archive_root, spec, capture, sha, read):
    capture_file = run / 'raw_evidence/ENVIRONMENT_CAPTURE.json'
    parent_file = run / 'CP6_PARENT_SPEC.json'
    assert sha(capture_file) == spec['environment_capture_sha256']
    assert capture == read(capture_file)
    assert sha(parent_file) == spec['source_hashes']['CP6_PARENT_SPEC.json']
    parent = read(parent_file)
    inherited = capture['dependency_hashes']
    assert inherited and inherited == parent['dependency_hashes'] == spec['dependency_hashes']
    for configuration in (parent, spec):
        cloud = PurePosixPath(configuration['cloud_root'])
        deps = PurePosixPath(configuration['dependencies_cloud'])
        assert cloud.is_absolute() and '..' not in cloud.parts
        assert deps == cloud / 'dependencies'
    assert capture['dependencies_cloud'] == parent['dependencies_cloud']
    files = {}
    for name, expected in inherited.items():
        relative = PurePosixPath(name)
        assert not relative.is_absolute() and '..' not in relative.parts and '\\' not in name
        frozen_name = 'dependencies/' + name
        assert spec['source_hashes'][frozen_name] == expected
        assert sha(run / frozen_name) == expected
        assert sha(archive_root / 'dependencies' / name) == expected
        files[name] = expected
    return dict(schema='frozen_parent_dependency_capture_relocation_v1', verified=True,
                parent_spec_sha256=sha(parent_file), capture_sha256=sha(capture_file),
                captured_cloud_root=parent['cloud_root'], executing_cloud_root=spec['cloud_root'],
                captured_dependencies_cloud=capture['dependencies_cloud'],
                executing_dependencies_cloud=spec['dependencies_cloud'], dependency_hashes=files)
