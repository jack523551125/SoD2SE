from __future__ import annotations

import hashlib
import unittest

from inspect_iggy_movie import IggyFormatError, inspect_iggy
from patch_iggy_text import patch_iggy_text
from test_iggy_movie_inspector import make_iggy


class IggyTextPatchTests(unittest.TestCase):
    def test_same_size_text_edit_changes_only_the_selected_string(self) -> None:
        source = make_iggy(text="Settings")
        source_hash = hashlib.sha256(source).hexdigest()
        old_text_hash = hashlib.sha256(b"Settings").hexdigest()
        replacement = "ModMenu!"

        patched, summary = patch_iggy_text(
            source,
            text_index=10,
            expected_source_sha256=source_hash,
            expected_text_sha256=old_text_hash,
            replacement=replacement,
        )

        original_report = inspect_iggy(source)
        patched_report = inspect_iggy(patched)
        self.assertEqual(len(patched), len(source))
        self.assertEqual(summary["utf16_code_units"], 8)
        self.assertTrue(summary["all_other_bytes_and_layouts_preserved"])
        self.assertEqual(
            patched,
            source[: summary["string_payload_offset"]]
            + replacement.encode("utf-16le")
            + source[summary["string_payload_offset"] + 16 :],
        )
        self.assertEqual(
            next(row for row in original_report["text_objects"] if row["text_index"] == 10)["bounds"],
            next(row for row in patched_report["text_objects"] if row["text_index"] == 10)["bounds"],
        )
        self.assertEqual(
            next(row for row in patched_report["text_objects"] if row["text_index"] == 10)["text_sha256"],
            hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn(replacement, str(patched_report))

    def test_rejects_unpinned_or_non_same_size_edits(self) -> None:
        source = make_iggy(text="Settings")
        source_hash = hashlib.sha256(source).hexdigest()
        text_hash = hashlib.sha256(b"Settings").hexdigest()
        with self.assertRaisesRegex(IggyFormatError, "caller-pinned source"):
            patch_iggy_text(
                source,
                text_index=10,
                expected_source_sha256="0" * 64,
                expected_text_sha256=text_hash,
                replacement="ModMenu!",
            )
        with self.assertRaisesRegex(IggyFormatError, "same UTF-16"):
            patch_iggy_text(
                source,
                text_index=10,
                expected_source_sha256=source_hash,
                expected_text_sha256=text_hash,
                replacement="Longer replacement",
            )
        with self.assertRaisesRegex(IggyFormatError, "text SHA-256"):
            patch_iggy_text(
                source,
                text_index=10,
                expected_source_sha256=source_hash,
                expected_text_sha256="0" * 64,
                replacement="ModMenu!",
            )


if __name__ == "__main__":
    unittest.main()
