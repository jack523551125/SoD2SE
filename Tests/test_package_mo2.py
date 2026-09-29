"""Package layout and version tests; no game files or MO2 instance required."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import package_mo2


class CatalogTests(unittest.TestCase):
    def test_real_catalog_covers_each_source_folder(self):
        mods = package_mo2.discover_mods()
        self.assertEqual({mod.id for mod in mods}, {
            'Mcm', 'MeleeSpeed', 'Roguelite', 'UnlimitedCommunity',
            'UnlimitedFollowers', 'NativeModSettingsEntry', 'SkipStartupIntro',
        })
        self.assertFalse(next(mod for mod in mods if mod.id == 'Roguelite').publish)
        self.assertEqual(package_mo2.framework_version(), '0.6.0-preview')

    def test_rejects_traversal_and_wrong_manifest_id(self):
        for path in ('../secret', '/absolute', 'Root\\Plugins\\Bad.dll', 'Root//Bad.dll'):
            with self.subTest(path=path), self.assertRaises(package_mo2.PackageError):
                package_mo2.safe_relative(path)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'Example'
            folder.mkdir()
            (folder / 'mod.json').write_text(json.dumps({
                'schema': 1, 'id': 'Other', 'name': 'Other', 'version': '1.0.0',
                'publish': True, 'requires': [],
                'files': [{'input': 'build:Plugins/Other.dll', 'target': 'Root/Plugins/Other.dll'}],
            }), encoding='utf-8')
            with self.assertRaises(package_mo2.PackageError):
                package_mo2.read_mod(folder / 'mod.json')

    def test_new_plugin_is_discovered_and_packaged_with_exact_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Plugins' / 'Example').mkdir(parents=True)
            (root / 'Mods').mkdir()
            (root / 'Core').mkdir()
            (root / 'Core' / 'SoD2SE.Core.cs').write_text(
                'public const string Version = "1.2.3-preview";', encoding='utf-8')
            (root / 'Plugins' / 'Example' / 'mod.json').write_text(json.dumps({
                'schema': 1, 'id': 'Example', 'name': '示例 - Example',
                'version': '2.3.4-preview', 'publish': True,
                'requires': ['SoD2SE Framework'],
                'files': [{'input': 'build:Plugins/Example.dll', 'target': 'Root/Plugins/Example.dll'}],
            }), encoding='utf-8')
            build = root / 'build'
            (build / 'Plugins').mkdir(parents=True)
            (build / 'Plugins' / 'Example.dll').write_bytes(b'example-binary')
            mod = package_mo2.discover_mods(root)[0]
            archive = package_mo2.package_mod(mod, root, build, root / 'output', {})
            with ZipFile(archive) as contents:
                self.assertEqual(set(contents.namelist()), {'meta.ini', 'Root/Plugins/Example.dll'})
                metadata = contents.read('meta.ini').decode('utf-8')
                self.assertIn('version=2.3.4-preview\n', metadata)
                self.assertIn('name=示例 - Example\n', metadata)
                self.assertIn('installationFile=SoD2-Example-MO2-v2.3.4-preview.zip\n', metadata)
                self.assertEqual(contents.read('Root/Plugins/Example.dll'), b'example-binary')
            with self.assertRaises(package_mo2.PackageError):
                package_mo2.package_mod(mod, root, build, root / 'output', {})

    def test_framework_package_has_no_mo2_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Core').mkdir()
            (root / 'Core' / 'SoD2SE.Core.cs').write_text(
                'public const string Version = "1.2.3-preview";', encoding='utf-8')
            build = root / 'build'
            build.mkdir()
            for name in ('SoD2SE.Loader.exe', 'SoD2SE.Core.dll', 'SoD2SE.GameApi.dll'):
                (build / name).write_bytes(name.encode('ascii'))
            archive = package_mo2.package_framework(root, build, root / 'output')
            with ZipFile(archive) as contents:
                self.assertEqual(set(contents.namelist()), {
                    'SoD2SE.Loader.exe', 'SoD2SE.Core.dll', 'SoD2SE.GameApi.dll',
                })

    def test_missing_later_input_does_not_leave_partial_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Plugins' / 'First').mkdir(parents=True)
            (root / 'Plugins' / 'Second').mkdir(parents=True)
            (root / 'Mods').mkdir()
            build = root / 'build'
            (build / 'Plugins').mkdir(parents=True)
            (build / 'Plugins' / 'First.dll').write_bytes(b'first')
            for mod_id in ('First', 'Second'):
                (root / 'Plugins' / mod_id / 'mod.json').write_text(json.dumps({
                    'schema': 1, 'id': mod_id, 'name': mod_id, 'version': '1.0.0',
                    'publish': True, 'requires': [],
                    'files': [{'input': f'build:Plugins/{mod_id}.dll',
                               'target': f'Root/Plugins/{mod_id}.dll'}],
                }), encoding='utf-8')
            output = root / 'output'
            with patch.object(package_mo2, 'SOURCE_ROOT', root):
                result = package_mo2.main(['--build-dir', str(build), '--output-dir', str(output),
                                           '--id', 'First', '--id', 'Second'])
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
