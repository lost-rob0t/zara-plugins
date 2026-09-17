"""Exercise actual APK renderer assets with a real VRM and software WebGL.

This is a browser-renderer E2E gate, not Android/OEM overlay acceptance.
Dependencies: playwright and Pillow. Chromium must be installed separately.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

CLOCK = """(() => {
 const queue = new Map(); let serial = 0, now = 0;
 window.requestAnimationFrame = fn => { queue.set(++serial, fn); return serial; };
 window.cancelAnimationFrame = id => queue.delete(id);
 window.__testFrames = n => {
  for(let i=0;i<n;i++) { now += 1000/30 + 0.01; const jobs=[...queue.values()]; queue.clear(); for(const fn of jobs) fn(now); }
  return queue.size;
 };
})();"""


def difference(a: bytes, b: bytes) -> int:
    x, y = Image.open(io.BytesIO(a)).convert('RGBA'), Image.open(io.BytesIO(b)).convert('RGBA')
    delta = ImageChops.difference(x, y).convert('RGB')
    return sum(max(pixel) > 12 for pixel in delta.getdata())



def run(apk: Path, model: Path, output: Path, chromium: str, source: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'Actual APK renderer + real VRM in Chromium software WebGL; NOT Android device E2E',
              'apk_sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
              'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
              'source_override': str(source) if source else None, 'checks': [], 'browser_errors': []}
    with tempfile.TemporaryDirectory(prefix='companion-e2e-') as temp:
        root = Path(temp)
        with zipfile.ZipFile(apk) as archive:
            for name in archive.namelist():
                if not name.startswith('assets/companion/') or name.endswith('/'):
                    continue
                relative = Path(name).relative_to('assets/companion')
                if '..' in relative.parts:
                    raise ValueError('unsafe archive path')
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
        if source:
            for path in source.glob('*'):
                if path.suffix in ('.mjs', '.css'):
                    shutil.copyfile(path, root / path.name)
        shutil.copyfile(model, root / 'avatar.vrm')
        origin = 'https://companion.zara.invalid'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=chromium, headless=True,
                    args=['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
                context = browser.new_context(viewport={'width': 420, 'height': 650}, device_scale_factor=1)
                blocked = []
                def route(request):
                    if request.request.url.startswith(origin + '/'):
                        relative = request.request.url[len(origin):].split('?', 1)[0].lstrip('/')
                        target = (root / relative).resolve()
                        if root.resolve() not in target.parents or not target.is_file():
                            request.fulfill(status=404, body='not found')
                        else:
                            mime = ('text/javascript' if target.suffix in ('.mjs', '.js') else
                                    'text/html' if target.suffix == '.html' else
                                    'text/css' if target.suffix == '.css' else 'application/octet-stream')
                            request.fulfill(status=200, content_type=mime, body=target.read_bytes())
                    else:
                        blocked.append(request.request.url)
                        request.abort()
                context.route('**/*', route)
                page = context.new_page()
                page.add_init_script(CLOCK)
                page.on('pageerror', lambda error: report['browser_errors'].append(str(error)))

                def check(name, condition, **detail):
                    report['checks'].append({'name': name, 'passed': bool(condition), **detail})
                    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
                    if not condition:
                        raise AssertionError(name + ': ' + json.dumps(detail))

                def step(n):
                    return page.evaluate('(n) => window.__testFrames(n)', n)

                def command(value):
                    return page.evaluate('(c) => window.companion.command(c)', value)

                def snapshot(name):
                    data = page.screenshot(omit_background=True, animations='allow')
                    (output / (name + '.png')).write_bytes(data)
                    return data

                def load():
                    page.goto(origin + '/index.html')
                    page.wait_for_function('window.companion?.ready === true', timeout=20000)

                load()
                check('VRM loaded with real loader', page.evaluate('window.companion.ready'))
                supported = page.evaluate('window.companion.supported')
                report['supported'] = supported
                step(60)
                neutral = snapshot('neutral')
                image = Image.open(io.BytesIO(neutral)).convert('RGBA')
                visible = sum(pixel[3] > 20 for pixel in image.getdata())
                check('nonblank transparent avatar', 1500 < visible < image.width * image.height * 0.75, visible_pixels=visible)
                for name in ('happy', 'sad', 'angry', 'relaxed', 'surprised', 'excited'):
                    load()
                    result = command({'type': 'emotion', 'name': name})
                    check('accept emotion ' + name, result == {'ok': True})
                    step(60)
                    changed = difference(neutral, snapshot(name))
                    check('visible emotion ' + name, changed > 15, changed_pixels=changed)
                for name in ('wave', 'nod', 'shake', 'dance_bounce', 'dance_sway', 'dance_step'):
                    load()
                    check('accept motion ' + name, command({'type': 'motion', 'name': name, 'loop': name.startswith('dance_')}) == {'ok': True})
                    step(60)
                    a = snapshot(name)
                    step(7)
                    b = snapshot(name + '-next')
                    check('motion differs from idle ' + name, difference(neutral, a) > 25, changed_pixels=difference(neutral, a))
                    check('motion advances ' + name, difference(a, b) > 10, changed_pixels=difference(a, b))
                check('stop command', command({'type': 'stop'}) == {'ok': True})
                step(20)
                snapshot('stopped')
                check('suspend', command({'type': 'active', 'value': False}) == {'ok': True})
                frozen = snapshot('paused')
                pending = step(120)
                check('paused frame stable and RAF stopped', pending == 0 and difference(frozen, snapshot('paused-later')) == 0)
                check('resume', command({'type': 'active', 'value': True}) == {'ok': True})
                step(30)
                check('resume animates', difference(frozen, snapshot('resumed')) > 10)
                check('unknown command rejected', command({'type': 'eval', 'code': 'alert(1)'}) == {'ok': False, 'error': 'invalid_command'})
                check('no external requests', not blocked, blocked=blocked)
                check('no browser exceptions', not report['browser_errors'])
                page.evaluate('window.companion.dispose()')
                check('disposed renderer rejects commands', command({'type': 'stop'}) == {'ok': False, 'error': 'renderer_closed'})
                # Force malformed actual model bytes, rather than mocking a successful VRM load.
                (root / 'avatar.vrm').write_bytes(b'invalid glb')
                page.goto(origin + '/index.html')
                page.wait_for_function("document.querySelector('#status').textContent.includes('unsupported')")
                check('invalid model remains unavailable', page.evaluate('window.companion.ready') is False)
                snapshot('invalid-model')
                browser.close()
        finally:
            report['passed'] = False
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    report['passed'] = all(check['passed'] for check in report['checks'])
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', default=shutil.which('chromium') or shutil.which('chromium-browser'))
    parser.add_argument('--source-web', type=Path)
    args = parser.parse_args()
    if not args.chromium:
        parser.error('A Chromium executable is required; use --chromium PATH')
    print(json.dumps(run(args.apk, args.model, args.output, args.chromium, args.source_web), indent=2))


if __name__ == '__main__':
    main()
