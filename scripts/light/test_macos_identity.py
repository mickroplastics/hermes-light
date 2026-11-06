"""Contract checks for identity isolation; no runtime or dependencies required."""
import json
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
import uuid

from macos_identity import stamp_bundle, uuid_offset


class IdentityTests(unittest.TestCase):
    def test_shared_electron_binary_gets_distinct_application_identities(self):
        original = uuid.uuid4()
        data = (struct.pack('<IIIIIIII', 0xFEEDFACF, 0x0100000C, 0, 2, 1, 24, 0, 0)
                + struct.pack('<II', 0x1B, 24) + original.bytes + b'unchanged code')
        with tempfile.TemporaryDirectory() as temp:
            identities = []
            for name in ('first', 'second'):
                app = Path(temp) / f'{name}.app'
                contents = app / 'Contents'
                (contents / 'MacOS').mkdir(parents=True)
                (contents / 'Resources').mkdir()
                (contents / 'Info.plist').write_bytes(plistlib.dumps({
                    'CFBundleIdentifier': f'example.{name}', 'CFBundleExecutable': name}))
                executable = contents / 'MacOS' / name
                executable.write_bytes(data)
                stamp_bundle(app)
                changed = executable.read_bytes()
                offset = uuid_offset(data)
                self.assertEqual(changed[:offset], data[:offset])
                self.assertEqual(changed[offset + 16:], data[offset + 16:])
                record = json.loads((contents / 'Resources/light-executable-uuids.json').read_text())[0]
                self.assertEqual(str(uuid.UUID(bytes=changed[offset:offset + 16])), record['uuid'])
                self.assertNotEqual(record['uuid'], str(original))
                identities.append(record['uuid'])
            self.assertNotEqual(*identities)

    def test_invalid_binary_fails_before_any_write(self):
        for data in (b'not Mach-O', struct.pack('<IIIIIIII', 0xFEEDFACF, 0, 0, 2, 1, 24, 0, 0)):
            with self.assertRaises(ValueError):
                uuid_offset(data)


if __name__ == '__main__':
    unittest.main()
