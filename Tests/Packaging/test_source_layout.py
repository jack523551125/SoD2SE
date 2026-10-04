"""Preserve provenance and standalone source-release lookup behavior."""
import tempfile
import unittest
from pathlib import Path

from Automation.source_layout import resolve, source_file, work_root


class SourceLayoutTests(unittest.TestCase):
    def test_unknown_provenance_preserves_windows_spelling(self):
        label = r'c:\ul\w\r\DaytonGame\Source\GameTelemetry\Private\EventTypes.cpp'
        self.assertEqual(resolve(label), label)

    def test_directory_provenance_resolves_descendants(self):
        self.assertEqual(
            resolve('Research/tools/native_settings_asset_writer/Program.cs'),
            '../../ReverseEngineering/Tools/UI/native_settings_asset_writer/Program.cs')

    def test_product_owner_provenance_resolves_across_repositories(self):
        self.assertEqual(
            resolve('Native/GrowthActorSource.cpp'),
            '../../Labs/Roguelite/native/src/GrowthActorSource.cpp')
        self.assertEqual(
            resolve('Native/MeleeNative.cpp'),
            '../../Projects/MeleeSpeed/native/src/MeleeNative.cpp')
        self.assertEqual(
            resolve('Research/StateOfDecay2/16535856/growth-actor-source.json'),
            '../../ReverseEngineering/Builds/16535856/growth-actor-source.json')

    def test_research_root_accepts_standalone_override(self):
        import os
        from unittest.mock import patch
        from Automation.source_layout import research_root
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {'SOD2_RESEARCH_ROOT': temporary}, clear=False):
                self.assertEqual(research_root(), Path(temporary).resolve())

    def test_release_source_fallback_and_missing_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / 'source/Native/src/Shared/PinnedImage.h'
            target.parent.mkdir(parents=True)
            target.write_text('fixture', encoding='utf-8')
            self.assertEqual(source_file(base, 'Native/PinnedImage.h'), target)
            with self.assertRaises(FileNotFoundError):
                source_file(base, 'Native/does-not-exist.h')

    def test_work_paths_follow_checkout_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'Projects/SoD2SE'
            source.mkdir(parents=True)
            self.assertEqual(work_root(source), source / '.work')
            (base / 'workspace.toml').write_text('schema = 1', encoding='utf-8')
            self.assertEqual(work_root(source), base / '.work/SoD2SE')
