"""Run real VRM integration against dependency files extracted from an APK."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def run(apk: Path, model: Path, report: Path) -> None:
    report = report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='companion-loader-') as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(apk) as z:
            for name in z.namelist():
                if not name.startswith('assets/companion/') or name.endswith('/'):
                    continue
                relative = Path(name).relative_to('assets/companion')
                if '..' in relative.parts:
                    raise ValueError('Unsafe APK asset path')
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(z.read(name))
        for entry in json.loads((root / 'dependencies.json').read_text()):
            digest = hashlib.sha256((root / entry['path']).read_bytes()).hexdigest()
            if digest != entry['sha256']:
                raise ValueError('APK dependency receipt mismatch')
        for directory, metadata in [
            ('vendor/three', {'name': 'three', 'type': 'module', 'exports': {'.': './build/three.module.js', './addons/*': './examples/jsm/*'}}),
            ('vendor/three-vrm', {'name': '@pixiv/three-vrm', 'type': 'module', 'exports': {'.': './three-vrm.module.js'}}),
        ]:
            (root / directory / 'package.json').write_text(json.dumps(metadata))
        (root / 'node_modules/@pixiv').mkdir(parents=True)
        (root / 'node_modules/three').symlink_to(root / 'vendor/three', target_is_directory=True)
        (root / 'node_modules/@pixiv/three-vrm').symlink_to(root / 'vendor/three-vrm', target_is_directory=True)
        shutil.copyfile(Path(__file__).with_name('loader_integration.mjs'), root / 'loader_integration.mjs')
        subprocess.run(['node', str(root / 'loader_integration.mjs'), str(model.resolve()), str(report)], check=True, timeout=30)
        evidence = json.loads(report.read_text())
        evidence.update(apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
                        model_sha256=hashlib.sha256(model.read_bytes()).hexdigest())
        report.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    run(args.apk, args.model, args.report)
