"""Validate and smoke-test the actual macOS app before preparing release files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

root = Path(__file__).resolve().parents[2]
release = root / 'apps/desktop/release'
apps = list(release.glob('mac*/Hermes Light.app'))
if len(apps) != 1:
    raise SystemExit(f'Expected one Hermes Light.app, found {apps}')
app = apps[0]


def verified_signature(bundle: Path) -> dict[str, str]:
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    details = subprocess.run(['codesign', '-dvvv', str(bundle)], check=True,
                             capture_output=True, text=True).stderr
    fields = dict(line.split('=', 1) for line in details.splitlines() if '=' in line)
    assert fields['Identifier'] == 'com.mickroplastics.hermes-light', fields
    assert fields['Signature'] == 'adhoc', fields
    assert 'runtime' in fields['CodeDirectory v'], fields
    records = json.loads((bundle / 'Contents/Resources/light-executable-uuids.json').read_text())
    assert len(records) >= 2, 'Main and helper identities must be isolated'
    assert len({r['uuid'] for r in records}) == len(records)
    for record in records:
        expected = uuid.uuid5(uuid.NAMESPACE_URL, f"{record['bundleId']}/{record['electronUuid']}")
        assert record['uuid'] == str(expected)
        assert record['uuid'] != record['electronUuid']
        actual = subprocess.run(['dwarfdump', '--uuid', str(bundle / record['path'])],
                                check=True, capture_output=True, text=True).stdout
        assert str(expected).upper() in actual, actual
    return fields


def artifact(suffix: str) -> Path:
    files = list(release.glob(f'HermesLight-*-mac-arm64.{suffix}'))
    if len(files) != 1:
        raise SystemExit(f'Expected one {suffix}, found {files}')
    return files[0]


resources = app / 'Contents/Resources'
stamp = json.loads((resources / 'install-stamp.json').read_text())
assert stamp['payload'] == 'light', stamp
assert stamp['commit'] == os.environ['GITHUB_SHA']
assert stamp['updateMechanism'] == 'external', stamp
assert not stamp.get('runtime'), 'Light must not carry a Python launch contract'
assert not (resources / 'agent-payload').exists(), 'Agent payload found'
signature = verified_signature(app)
out = root / 'light-release'
out.mkdir(exist_ok=True)
prepared = json.loads((root / '.build/desktop-job/prepared.json').read_text())
node = prepared['node']
# Verify what users receive: a seal on the build directory proves nothing about
# archives. Each must hold the same signed code; the smoke runs the DMG's copy.
with tempfile.TemporaryDirectory() as temp:
    work = Path(temp)
    subprocess.run(['ditto', '-x', '-k', str(artifact('zip')), str(work / 'zip')], check=True)
    assert verified_signature(work / 'zip/Hermes Light.app')['CDHash'] == signature['CDHash']
    subprocess.run(['hdiutil', 'verify', str(artifact('dmg'))], check=True)
    mount = work / 'dmg'
    mount.mkdir()
    subprocess.run(['hdiutil', 'attach', '-nobrowse', '-readonly', '-mountpoint', str(mount),
                    str(artifact('dmg'))], check=True)
    try:
        subprocess.run(['ditto', str(mount / 'Hermes Light.app'),
                        str(work / 'installed/Hermes Light.app')], check=True)
    finally:
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
    installed = work / 'installed/Hermes Light.app'
    assert verified_signature(installed)['CDHash'] == signature['CDHash']
    subprocess.run([node, 'scripts/light/smoke.mjs', str(installed), str(out)], cwd=root, check=True)
    # The smoke must not have changed the sealed bundle.
    assert verified_signature(installed)['CDHash'] == signature['CDHash']
for suffix in ('dmg', 'zip'):
    shutil.copy2(artifact(suffix), out / f'HermesLight-macos-arm64.{suffix}')
(out / 'build.json').write_text(json.dumps(stamp, indent=2) + '\n')
(out / 'SHA256SUMS').write_text(''.join(
    f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
    for p in sorted(out.glob('HermesLight-*'))))
(out / 'INSTALL.md').write_text(f'''# Hermes Light for Apple Silicon Macs

Community build from the Nous Research Hermes Desktop source, maintained in
`mickroplastics/hermes-light`. This is not an official Nous release.

1. Download `HermesLight-macos-arm64.dmg` and open it.
2. Drag **Hermes Light** into Applications.
3. Open it and enter your existing Hermes server URL, then sign in.

Requires macOS 13 or newer and an Apple Silicon Mac. The app is ad-hoc signed,
not Apple-notarized. macOS may require **System Settings → Privacy & Security →
Open Anyway** after the first launch attempt. No Apple Developer credentials
are used by this workflow.

This client contains no Python/agent payload, refuses local runtime installation
and startup, and opens directly into remote connection setup. The packaged app
passed the attached startup and local-install denial checks in CI.

Updates are manual: download the newest release and replace the app. Automatic
updating is disabled so this build cannot replace itself with the full runtime.
The bundle ID and settings location remain stable. Ad-hoc signing can cause macOS
to ask for permissions again after an update. Executable UUIDs are isolated from
other Electron apps so Local Network permissions can identify this app correctly.
Server configuration and credentials are never baked into the download.

Source commit: `{stamp['commit']}`. Upstream base: `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`.
''')
