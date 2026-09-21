"""UI-driven Android smoke test for the exact Companion APK.

Requires a dedicated, unlocked, English-language test device. Imports replace the
selected Companion avatar. --emulator permits test-only overlay permission changes
only after the device reports ro.kernel.qemu=1. On hardware grant overlay access
in Android Settings yourself before running. Screenshots require visual review;
this smoke test does not classify emotion/dance pixels or prove host integration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

PACKAGE = 'ai.zara.companion'
ACTIVITY = PACKAGE + '/.CompanionActivity'
REMOTE_MODEL = '/sdcard/Download/Zara-Companion-E2E.vrm'
REMOTE_XML = '/data/local/tmp/zara-companion-e2e.xml'


def center(bounds: str) -> tuple[int, int]:
    values = re.fullmatch(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]', bounds)
    if not values:
        raise ValueError('Invalid UI bounds')
    x1, y1, x2, y2 = map(int, values.groups())
    if x2 <= x1 or y2 <= y1:
        raise ValueError('Empty UI bounds')
    return x1 + (x2 - x1) // 4, (y1 + y2) // 2


def overlay_windows(text: str) -> list[str]:
    return [part for part in re.split(r'\n\s*Window #\d+', text)[1:]
            if PACKAGE in part.splitlines()[0] and re.search(r'(?:ty|type)=(?:APPLICATION_OVERLAY|2038)\b', part)]


class Device:
    def __init__(self, serial: str):
        self.prefix = ['adb', '-s', serial]

    def run(self, *args: str, timeout: int = 30) -> bytes:
        result = subprocess.run(self.prefix + list(args), capture_output=True, timeout=timeout, check=True)
        return result.stdout

    def shell(self, *args: str) -> str:
        return self.run('shell', *args).decode('utf-8', errors='replace')

    def ui(self):
        self.shell('uiautomator', 'dump', '--compressed', REMOTE_XML)
        return ET.fromstring(self.shell('cat', REMOTE_XML))

    def dimensions(self):
        matches = re.findall(r'(\d+)x(\d+)', self.shell('wm', 'size'))
        if not matches:
            raise RuntimeError('Device dimensions unavailable')
        return tuple(map(int, matches[-1]))

    def swipe(self, down: bool):
        w, h = self.dimensions()
        start, end = ((h // 4, h * 3 // 4) if down else (h * 3 // 4, h // 4))
        self.shell('input', 'swipe', str(w // 4), str(start), str(w // 4), str(end), '220')

    def find(self, labels: tuple[str, ...], scroll: bool = False):
        wanted = {label.casefold() for label in labels}
        for _ in range(10 if scroll else 1):
            for node in self.ui().iter('node'):
                values = (node.get('text', '').casefold(), node.get('content-desc', '').casefold())
                if wanted.intersection(values) and node.get('enabled') == 'true':
                    try:
                        return center(node.get('bounds', ''))
                    except ValueError:
                        continue
            if scroll:
                self.swipe(False)
        return None

    def tap(self, *labels: str, scroll: bool = True):
        found = self.find(tuple(labels), scroll)
        if not found and scroll:
            for _ in range(10):
                self.swipe(True)
            found = self.find(tuple(labels), True)
        if not found:
            raise AssertionError('UI control not found: ' + repr(labels))
        self.shell('input', 'tap', str(found[0]), str(found[1]))

    def launch(self):
        self.shell('am', 'start', '-W', '-n', ACTIVITY)

    def windows(self):
        return overlay_windows(self.shell('dumpsys', 'window', 'windows'))


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence = {'scope': 'Android UI/SAF/window smoke; screenshots need visual review; not Zara host E2E',
                'status': 'running', 'checks': [], 'emulator': args.emulator,
                'apk_sha256': hashlib.sha256(args.apk.read_bytes()).hexdigest(),
                'model_sha256': hashlib.sha256(args.model.read_bytes()).hexdigest(),
                'manual_gates': ['Pixel/animation review', 'Tap through to a different app UID',
                                 'Lock/unlock and rotation', 'Thermal and battery behavior',
                                 'Zara #924 authenticated host/Prolog integration']}
    def save():
        (output / 'report.json').write_text(json.dumps(evidence, indent=2) + '\n')
    def check(name, ok):
        evidence['checks'].append({'name': name, 'passed': bool(ok)})
        save()
        if not ok:
            raise AssertionError(name)
    def wait(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.25)
        return False
    device = Device(args.serial)
    prepared = False
    try:
        check('selected ADB device is authorized', device.run('get-state').strip() == b'device')
        if args.emulator:
            check('test permission setup is emulator-only', device.shell('getprop', 'ro.kernel.qemu').strip() == '1')
        if args.install:
            check('exact candidate APK installed', 'Success' in device.run('install', '-r', str(args.apk.resolve()), timeout=120).decode())
        package_path = device.shell('pm', 'path', PACKAGE).strip().removeprefix('package:')
        check('single APK package present', package_path.startswith('/') and '\n' not in package_path)
        installed = output / 'installed.apk'
        device.run('pull', package_path, str(installed), timeout=60)
        check('installed APK matches supplied candidate SHA256', hashlib.sha256(installed.read_bytes()).hexdigest() == evidence['apk_sha256'])
        installed.unlink()
        if args.emulator:
            device.shell('appops', 'set', PACKAGE, 'SYSTEM_ALERT_WINDOW', 'allow')
            prepared = True
        check('overlay permission granted', 'allow' in device.shell('appops', 'get', PACKAGE, 'SYSTEM_ALERT_WINDOW').lower())
        device.run('push', str(args.model.resolve()), REMOTE_MODEL)
        device.launch()
        with zipfile.ZipFile(args.apk) as archive:
            bundled = archive.read('assets/default-avatar.vrm')
        check('candidate bundles a bounded default VRM', 32 <= len(bundled) <= 1024 * 1024)
        device.tap('Use bundled test bot')
        check('bundled avatar selection completes', wait(lambda: any('Imported.' in n.get('text', '') for n in device.ui().iter('node'))))
        selected = device.shell('run-as', PACKAGE, 'sha256sum', 'files/avatar.vrm').split()[0]
        check('bundled selection imports actual APK model bytes', selected == hashlib.sha256(bundled).hexdigest())
        device.tap('Import VRM (maximum 32 MiB)')
        if not device.find(('Zara-Companion-E2E.vrm',)):
            device.tap('Show roots', 'Open navigation drawer', 'Show navigation drawer', scroll=False)
            device.tap('Downloads', 'Download', scroll=False)
        device.tap('Zara-Companion-E2E.vrm')
        check('SAF import completes', wait(lambda: any('Imported.' in n.get('text', '') for n in device.ui().iter('node'))))
        imported = device.shell('run-as', PACKAGE, 'sha256sum', 'files/avatar.vrm').split()[0]
        check('actual imported bytes match fixture', imported == evidence['model_sha256'])
        device.tap('Show companion')
        check('application overlay exists', wait(lambda: bool(device.windows())))
        check('default window is non-touchable', any('NOT_TOUCHABLE' in w for w in device.windows()))
        # Loading fails closed after 20 s in alpha.1; do not mistake the initial window for readiness.
        deadline = time.monotonic() + 22
        while time.monotonic() < deadline:
            if not device.windows():
                raise AssertionError('Renderer window disappeared before load timeout')
            time.sleep(0.5)
        check('overlay survives renderer load timeout (liveness only)', bool(device.windows()))
        for label in ['Wave', 'Nod', 'Shake head', 'Dance: bounce', 'Dance: sway', 'Dance: step'] + [
            'Emotion: ' + name for name in ('neutral', 'happy', 'sad', 'angry', 'relaxed', 'surprised', 'excited')]:
            device.tap(label)
            time.sleep(0.4)
            check('UI action preserves overlay: ' + label, bool(device.windows()))
            name = re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')
            (output / (name + '.png')).write_bytes(device.run('exec-out', 'screencap', '-p'))
        device.tap('Idle / stop dancing and talking')
        check('stop keeps companion visible', bool(device.windows()))
        device.tap('Dance to genre + tempo')
        check('genre/tempo dance keeps companion visible', wait(lambda: bool(device.windows())))
        device.tap('Like this move')
        def learned_feedback():
            return 'dance.score.' in device.shell('run-as', PACKAGE, 'cat', 'shared_prefs/companion.xml')
        check('dance feedback persists locally', wait(learned_feedback))
        device.tap('Skip / teach another move')
        check('learned skip starts another bounded dance', wait(lambda: bool(device.windows())))
        device.tap('Move avatar: toggle drag / click-through')
        check('edit mode removes non-touchable flag', wait(lambda: bool(device.windows()) and all('NOT_TOUCHABLE' not in w for w in device.windows())))
        device.tap('Move avatar: toggle drag / click-through')
        check('click-through mode restored', wait(lambda: any('NOT_TOUCHABLE' in w for w in device.windows())))
        device.shell('am', 'start', '-W', '-a', 'android.settings.SETTINGS')
        check('overlay survives opening another app', bool(device.windows()))
        (output / 'overlay-over-settings.png').write_bytes(device.run('exec-out', 'screencap', '-p'))
        device.launch()
        device.tap('Hide companion')
        check('hide removes overlay', wait(lambda: not device.windows()))
        device.tap('Show companion')
        check('show recreates overlay', wait(lambda: bool(device.windows())))
        if args.emulator:
            device.shell('appops', 'set', PACKAGE, 'SYSTEM_ALERT_WINDOW', 'deny')
            check('permission revocation removes overlay', wait(lambda: not device.windows()))
        evidence['status'] = 'passed_smoke_visual_review_pending'
    except Exception as error:
        evidence['status'] = 'failed_or_blocked'
        evidence['error'] = type(error).__name__ + ': ' + str(error)[:1200]
        try:
            webview = device.shell('dumpsys', 'webviewupdate')
            evidence['webview_update'] = webview[-6000:]
            (output / 'webview-update.txt').write_text(webview)
        except Exception as diagnostic_error:
            evidence['webview_update_error'] = type(diagnostic_error).__name__
        try:
            prefs = device.shell('run-as', PACKAGE, 'cat', 'shared_prefs/companion.xml')
            evidence['companion_preferences'] = prefs[-6000:]
            (output / 'companion-preferences.xml').write_text(prefs)
        except Exception as diagnostic_error:
            evidence['preferences_error'] = type(diagnostic_error).__name__
        try:
            logcat = device.shell('logcat', '-d', '-t', '2000', '-v', 'brief')
            tokens = ('chromium', 'webview', 'zara companion', 'zaracompanion',
                      'ai.zara.companion', 'javascript', 'console', 'cr_')
            relevant = '\n'.join(
                line for line in logcat.splitlines()
                if any(token in line.lower() for token in tokens)
            )
            (output / 'webview-logcat.txt').write_text(relevant + '\n')
            evidence['webview_log_tail'] = relevant[-12000:]
            if relevant:
                print('--- Companion WebView diagnostics ---')
                print(relevant[-12000:])
        except Exception as diagnostic_error:
            evidence['logcat_error'] = type(diagnostic_error).__name__
        save()
        raise
    finally:
        save()
        if prepared:
            device.shell('am', 'force-stop', PACKAGE)
            device.shell('appops', 'set', PACKAGE, 'SYSTEM_ALERT_WINDOW', 'allow')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--emulator', action='store_true')
    parser.add_argument('--test-device-consent', action='store_true', help='Confirm this is an unlocked test device; avatar selection will be replaced.')
    args = parser.parse_args()
    if not args.test_device_consent:
        parser.error('--test-device-consent is required; do not run against an unprepared daily-use device')
    run(args)
