"""Give Light its own Mach-O UUIDs before signing (Apple TN3179).

Electron's prebuilt executable UUIDs are shared by unrelated apps. macOS uses
them for Local Network privacy, so a bundle identifier alone is not sufficient.
"""
import json
from pathlib import Path
import plistlib
import struct
import sys
import uuid


def uuid_offset(data: bytes) -> int:
    if data[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('Expected a thin 64-bit little-endian Mach-O executable')
    count, size = struct.unpack_from('<II', data, 16)
    offset, end = 32, 32 + size
    if end > len(data):
        raise ValueError('Truncated Mach-O commands')
    offsets = []
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError('Truncated Mach-O command')
        command, length = struct.unpack_from('<II', data, offset)
        if length < 8 or offset + length > end:
            raise ValueError('Invalid Mach-O command length')
        if command == 0x1B:  # LC_UUID
            if length != 24:
                raise ValueError('Invalid LC_UUID length')
            offsets.append(offset + 8)
        offset += length
    if len(offsets) != 1 or offset != end:
        raise ValueError('Expected exactly one LC_UUID and complete commands')
    return offsets[0]


def stamp_bundle(app: Path) -> None:
    manifest = app / 'Contents/Resources/light-executable-uuids.json'
    if manifest.exists():
        raise ValueError('Identity stamp already exists; use a fresh package')
    records = []
    for bundle in [app, *sorted(app.glob('Contents/Frameworks/*.app'))]:
        info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
        executable = bundle / 'Contents/MacOS' / info['CFBundleExecutable']
        data = bytearray(executable.read_bytes())
        offset = uuid_offset(data)
        original = uuid.UUID(bytes=bytes(data[offset:offset + 16]))
        assigned = uuid.uuid5(uuid.NAMESPACE_URL, f"{info['CFBundleIdentifier']}/{original}")
        data[offset:offset + 16] = assigned.bytes
        executable.write_bytes(data)
        records.append({'path': str(executable.relative_to(app)),
                        'bundleId': info['CFBundleIdentifier'],
                        'electronUuid': str(original), 'uuid': str(assigned)})
    if len({r['uuid'] for r in records}) != len(records):
        raise ValueError('Duplicate executable identities')
    manifest.write_text(json.dumps(records, indent=2) + '\n')
    print(f'[light] assigned distinct Mach-O UUIDs to {len(records)} executables')


if __name__ == '__main__':
    stamp_bundle(Path(sys.argv[1]))
