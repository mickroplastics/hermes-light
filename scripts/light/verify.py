"""Validate and smoke-test the actual macOS app before preparing release files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[2]
release = root / 'apps/desktop/release'
apps = list(release.glob('mac*/Hermes Light.app'))
if len(apps) != 1:
    raise SystemExit(f'Expected one Hermes Light.app, found {apps}')
app = apps[0]
resources = app / 'Contents/Resources'
stamp = json.loads((resources / 'install-stamp.json').read_text())
assert stamp['payload'] == 'light', stamp
assert stamp['commit'] == os.environ['GITHUB_SHA']
assert stamp['updateMechanism'] == 'external', stamp
assert not stamp.get('runtime'), 'Light must not carry a Python launch contract'
assert not (resources / 'agent-payload').exists(), 'Agent payload found'
subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
out = root / 'light-release'
out.mkdir(exist_ok=True)
prepared = json.loads((root / '.build/desktop-job/prepared.json').read_text())
node = prepared['node']
subprocess.run([node, 'scripts/light/smoke.mjs', str(app), str(out)], cwd=root, check=True)
for suffix in ('dmg', 'zip'):
    files = list(release.glob(f'HermesLight-*-mac-arm64.{suffix}'))
    if len(files) != 1:
        raise SystemExit(f'Expected one {suffix}, found {files}')
    shutil.copy2(files[0], out / f'HermesLight-macos-arm64.{suffix}')
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
The application identity remains stable across releases to preserve sign-in and
settings. Server configuration and credentials are never baked into the download.

Source commit: `{stamp['commit']}`. Upstream base: `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`.
''')
