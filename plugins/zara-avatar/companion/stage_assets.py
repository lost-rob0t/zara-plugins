"""Stage the existing lockfile-pinned renderer dependencies; never fetch at runtime."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

BASE = Path(__file__).resolve().parent
FILES = {
    "three": ["build/three.module.js", "build/three.core.js", "examples/jsm/loaders/GLTFLoader.js", "examples/jsm/utils/BufferGeometryUtils.js", "LICENSE"],
    "@pixiv/three-vrm": ["lib/three-vrm.module.js", "LICENSE"],
}

def stage(output: Path, renderer: Path = BASE.parent / "renderer") -> None:
    lock = json.loads((renderer / "package-lock.json").read_text())
    selected = []
    for package, names in FILES.items():
        source = renderer / "node_modules" / package
        metadata = json.loads((source / "package.json").read_text())
        pinned = lock["packages"]["node_modules/" + package]
        if metadata["version"] != pinned["version"] or not pinned.get("integrity", "").startswith("sha512-"):
            raise ValueError("Renderer dependencies differ from the integrity-pinned lockfile")
        for name in names:
            path = source / name
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"Missing renderer asset: {package}/{name}; run npm ci --omit=dev --ignore-scripts")
            target = Path("vendor/three") / name if package == "three" else Path("vendor/three-vrm") / Path(name).name
            selected.append((path, target, package, pinned["version"], pinned["integrity"]))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="companion-assets-", dir=output.parent) as work:
        root = Path(work) / "companion"
        root.mkdir()
        for path in (BASE / "web").iterdir():
            if path.is_file(): shutil.copyfile(path, root / path.name)
        receipt = []
        for source, relative, package, version, integrity in selected:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            receipt.append({"path": str(relative), "package": package, "version": version,
                            "npm_integrity": integrity, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        imports = json.dumps({"imports": {"three": "/vendor/three/build/three.module.js",
            "three/addons/": "/vendor/three/examples/jsm/", "@pixiv/three-vrm": "/vendor/three-vrm/three-vrm.module.js"}}, separators=(",", ":"))
        script_hash = base64.b64encode(hashlib.sha256(imports.encode()).digest()).decode()
        (root / "index.html").write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'sha256-{script_hash}'; style-src 'self'; img-src blob: data:; connect-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>Zara Companion</title><link rel="stylesheet" href="/style.css">
<script type="importmap">{imports}</script><script type="module" src="/scene.mjs"></script>
</head><body><div id="status" role="status">Loading avatar…</div></body></html>''')
        (root / "dependencies.json").write_text(json.dumps(receipt, indent=2) + "\n")
        destination = output / "companion"
        if destination.exists(): shutil.rmtree(destination)
        shutil.move(str(root), destination)

if __name__ == "__main__":
    if len(sys.argv) != 2: raise SystemExit("Usage: python3 stage_assets.py OUTPUT_DIRECTORY")
    stage(Path(sys.argv[1]))
