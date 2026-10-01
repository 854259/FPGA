"""Read-only Linux preflight; refuses to install when measured free space is low."""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys

ap = argparse.ArgumentParser()
ap.add_argument('installer', type=pathlib.Path)
ap.add_argument('--workspace', type=pathlib.Path, default=pathlib.Path('/workspace'))
ap.add_argument('--bom', type=pathlib.Path, required=True)
args = ap.parse_args()
if sys.platform != 'linux':
    raise SystemExit('Run on the target Linux instance, not the local Windows machine.')
bom = json.loads(args.bom.read_text())
expanded = sum(a['expanded_bytes'] for a in bom['archives'])
reserve = 8 * 1024**3
required = expanded + reserve
usage = shutil.disk_usage(args.workspace)
print(json.dumps({'total_bytes':usage.total, 'used_bytes':usage.used,
                  'free_bytes':usage.free, 'metadata_install_bytes':expanded,
                  'temporary_and_margin_bytes':reserve,
                  'minimum_free_after_upload_bytes':required}, indent=2))
if usage.free < required:
    raise SystemExit('STOP: insufficient measured free space after upload. Do not install or download model.')
for a in bom['archives']:
    p = args.installer / 'payload' / (a['archive'] + '.xz')
    if not p.is_file() or p.stat().st_size != a['compressed_bytes']:
        raise SystemExit('STOP: missing or wrong-size payload ' + str(p))
    with p.open('rb') as f:
        h = hashlib.md5()
        for chunk in iter(lambda: f.read(8*1024*1024), b''):
            h.update(chunk)
        digest = h.hexdigest()
    if digest.lower() != a['md5'].lower():
        raise SystemExit('STOP: corrupt payload ' + str(p))
print('PAYLOAD_AND_SPACE_PREFLIGHT_PASS')
print('This checks metadata and free space only; vendor install, license, simulation and synthesis still require validation.')
