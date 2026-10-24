"""Opt-in end-to-end checks of the three drawer-to-window handoffs."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live', action='store_true', required=True,
                    help='operate temporary windows, the central, and a temporary workspace')
parser.parse_args()
root = Path(__file__).resolve().parents[2]
pointer = root / 'tests/desktop/virtual-pointer'
fixture = root / 'tests/desktop/fixture.py'
app_id = 'caelestia-surface-motion-test'
entry = Path.home() / '.local/share/applications' / (app_id + '.desktop')


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


def ipc(target, method, *args):
    return run('qs', '-c', 'caelestia', 'ipc', 'call', target, method, *args)


def clients():
    return json.loads(run('hyprctl', 'clients', '-j'))


def panel():
    return json.loads(ipc('minimized', 'info'))


def bubble():
    return json.loads(ipc('windowbubble', 'info'))


def wait(predicate, message, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.015)
    raise AssertionError(message)


def click(x, y):
    run(str(pointer), str(round(x)), str(round(y)), '0', 'click')


def state(client):
    address = client['address'].removeprefix('0x')
    code = f'local s=hl.plugin.caelestia_minimize.animation_state("{address}",{client["pid"]}); '
    code += 'return string.format("%.5f %.5f %.5f %.5f %.5f %.5f %.5f %.5f %.5f %.5f",s.x,s.y,s.width,s.height,s.targetX,s.targetY,s.targetWidth,s.targetHeight,s.fadeAlpha,s.minimizeProgress)'
    return [float(v) for v in run('hyprctl', 'repl', code).split()]


def sample(client, minimized=False):
    samples, surfaces = [], []
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = state(client)
        samples.append(value)
        surfaces.extend(bubble()['active'])
        current = next(c for c in clients() if c['address'] == client['address'])
        if minimized and current['workspace']['name'] == 'special:caelestia-minimized':
            break
        if not minimized and value[9] < 0 and any(s[9] >= 0 for s in samples):
            break
        time.sleep(.005)
    assert any(s[8] < .01 and 0 <= s[9] < .74 for s in samples), ('Missing material handoff', samples[:8], samples[-2:])
    assert any(s['clientAlpha'] == 0 and s['windowWidth'] >= 80 for s in surfaces), 'Missing shell surface'
    if minimized:
        assert current['workspace']['name'] == 'special:caelestia-minimized'
    else:
        assert all(abs(samples[-1][i] - samples[-1][i + 4]) < .1 for i in range(4))
    wait(lambda: not bubble()['active'], 'Stale material surface')
    return {'passed': True, 'nativeSamples': len(samples), 'surfaceSamples': len(surfaces)}


def desktop_arg(value):
    text = str(value).replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        text = text.replace(char, '\\' + char)
    return '"' + text + '"'


assert pointer.is_file(), 'Build tests/desktop/virtual-pointer first'
assert ipc('lock', 'isLocked') == 'false'
assert not entry.exists(), 'Temporary desktop entry already exists'
assert not any(c['workspace']['name'] == '918' or c['title'] == 'Central Demo Alpha' for c in clients())
monitor = next(m for m in json.loads(run('hyprctl', 'monitors', '-j')) if m['focused'])
assert (monitor['x'], monitor['y'], monitor['width'], monitor['height'], monitor['scale']) == (0, 0, 1920, 1080, 1), 'Pointer fixture requires the supported 1920x1080 desktop'
before = panel()
cursor = json.loads(run('hyprctl', 'cursorpos', '-j'))
active = json.loads(run('hyprctl', 'activewindow', '-j'))
workspace = json.loads(run('hyprctl', 'activeworkspace', '-j'))['name']
originals = {(c['address'], c['pid']) for c in clients()}
original_entries = json.loads(ipc('minimized', 'list'))
reports = []
favorited = False
owned = None
try:
    run('hyprctl', 'dispatch', 'hl.dsp.focus({workspace="918"})')
    time.sleep(.6)
    with tempfile.TemporaryDirectory(prefix='central-surface-test-') as directory:
        control = Path(directory) / 'control.json'
        for backend in ('wayland', 'x11'):
            control.unlink(missing_ok=True)
            command = ['env', 'GDK_BACKEND=' + backend, 'python3', str(fixture), '--single', '--control', str(control)]
            print(backend + ': starting baseline', flush=True)
            # An ordinary launcher must retain the compositor's own animation.
            run('hyprctl', 'dispatch', 'hl.dsp.exec_cmd(' + json.dumps(shlex.join(command)) + ',{workspace="918 silent",no_focus=true})')
            owned = wait(lambda: next((c for c in clients() if c['title'] == 'Central Demo Alpha'), None), 'Baseline fixture missing')
            for _ in range(12):
                value = state(owned)
                assert value[9] == -1, ('Unarmed launch used the surface animation', backend, value, run('hyprctl', 'repl', 'local s=hl.plugin.caelestia_minimize.launch_state(); return string.format("pending=%s address=%s",s.pending,s.address)'))
                time.sleep(.01)
            run('hyprctl', 'dispatch', 'hl.dsp.window.close({window=' + json.dumps('address:' + owned['address']) + '})')
            wait(lambda: not any(c['pid'] == owned['pid'] for c in clients()), 'Baseline fixture did not close')
            owned = None
            entry.parent.mkdir(parents=True, exist_ok=True)
            startup_class = 'io.github.luancaldeira.CentralMotionTest' if backend == 'wayland' else 'caelestia-central-motion-test'
            entry.write_text('[Desktop Entry]\nType=Application\nName=Zzz Surface Test\nIcon=applications-graphics\nTerminal=false\nStartupWMClass=' + startup_class + '\nExec=' + ' '.join(desktop_arg(v) for v in command) + '\n')
            wait(lambda: any(e['id'] == app_id for e in json.loads(ipc('appcentral', 'list'))), 'Desktop entry missing')
            ipc('appcentral', 'favorite', app_id)
            favorited = True
            if not panel()['open']:
                ipc('minimized', 'toggle')
            ipc('minimized', 'tab', '0')
            time.sleep(.65)
            p = panel()
            index = p['icons'].index(app_id)
            columns = min(12, int((min(600, monitor['width'] - 100) - 14) / 46))
            click(p['mini']['x'] + 30 + index % columns * 46, p['mini']['y'] + 28 + index // columns * 46)
            owned = wait(lambda: next((c for c in clients() if c['title'] == 'Central Demo Alpha'), None), 'Hub launch did not open fixture')
            report = {'backend': backend, 'unarmedLaunchUnchanged': True, 'appHub': sample(owned)}
            original = next(c for c in clients() if c['address'] == owned['address'])
            control.write_text(json.dumps({'sequence': time.time_ns(), 'action': 'minimize', 'window': 'Alpha'}))
            report['minimize'] = sample(owned, minimized=True)
            if not panel()['open']:
                ipc('minimized', 'toggle')
            ipc('minimized', 'tab', '1')
            time.sleep(.65)
            address = owned['address'][2:]
            for method in ('next', 'previous'):
                for _ in range(len(json.loads(ipc('minimized', 'list'))) + 1):
                    if panel().get('selected') == address:
                        break
                    ipc('minimized', method)
                if panel().get('selected') == address:
                    break
            assert panel().get('selected') == address
            time.sleep(.35)
            origin = panel()['origin']
            x, y = origin['x'] + origin['width'] / 2, origin['y'] + origin['height'] / 2
            click(x, y)
            report['windowsHub'] = sample(owned)
            assert panel()['open'] and panel()['tab'] == 1
            current_cursor = json.loads(run('hyprctl', 'cursorpos', '-j'))
            assert abs(current_cursor['x'] - round(x)) < 2 and abs(current_cursor['y'] - round(y)) < 2
            current = next(c for c in clients() if c['address'] == owned['address'])
            assert current['at'] == original['at'] and current['size'] == original['size']
            report.update(hubKeptOpen=True, pointerPreserved=True, originalGeometryPreserved=True)
            reports.append(report)
            os.kill(owned['pid'], 15)
            wait(lambda: not any(c['pid'] == owned['pid'] for c in clients()), 'Fixture cleanup failed')
            owned = None
            ipc('appcentral', 'favorite', app_id)
            favorited = False
            entry.unlink()
            wait(lambda: not any(e['id'] == app_id for e in json.loads(ipc('appcentral', 'list'))), 'Desktop entry cleanup failed')
            print(backend + ': all three surface handoffs passed', flush=True)
finally:
    if owned and any(c['address'] == owned['address'] and c['pid'] == owned['pid'] for c in clients()):
        os.kill(owned['pid'], 15)
    if favorited:
        ipc('appcentral', 'favorite', app_id)
    entry.unlink(missing_ok=True)
    if panel()['open']:
        ipc('minimized', 'toggle')
    target = {'window': 'address:' + active['address']} if active.get('address') else {'workspace': workspace}
    run('hyprctl', 'dispatch', 'hl.dsp.focus(' + '{' + ','.join(k + '=' + json.dumps(v) for k, v in target.items()) + '})')
    if before['open']:
        ipc('minimized', 'toggle')
        ipc('minimized', 'tab', str(before['tab']))
        if before['tab'] == 0 and before['menuOpen']:
            time.sleep(.6)
            p = panel()['handle']
            click(p['x'], p['y'])
    run(str(pointer), str(cursor['x']), str(cursor['y']))
assert originals <= {(c['address'], c['pid']) for c in clients()}, 'An original window disappeared'
assert {(e['address'], e['pid']) for e in json.loads(ipc('minimized', 'list'))} == {(e['address'], e['pid']) for e in original_entries}
(root / 'test-results').mkdir(exist_ok=True)
(root / 'test-results/surface-motion.json').write_text(json.dumps({'passed': True, 'cases': reports}, indent=2))
print('Desktop state preserved; no screenshots or recordings used.')
