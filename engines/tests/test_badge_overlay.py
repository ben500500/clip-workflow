#!/usr/bin/env python3
"""角标 overlay 像素偏移的回归测试（不执行 ffmpeg）。"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock


_ENGINES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SPEC = importlib.util.spec_from_file_location(
    "slice_mod", os.path.join(_ENGINES_DIR, "slice.py")
)
slice_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(slice_mod)


class BadgeOverlayOffsetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.badge_path = os.path.join(self.tmp.name, "badge.png")
        # build_badges_overlay_args 只校验文件存在，不读取或编码图片内容。
        with open(self.badge_path, "wb") as badge_file:
            badge_file.write(b"badge test fixture")

    def assert_top_right_overlay(self, badge, expected_overlay):
        with mock.patch.object(
            slice_mod, "build_encoder_args", return_value=["-c:v", "mock"]
        ) as encoder_mock:
            args = slice_mod.build_badges_overlay_args(
                [dict(path=self.badge_path, position="top-right", **badge)],
                threads=2,
                encoder="libx264",
            )

        encoder_mock.assert_called_once_with("libx264", 2)
        filter_complex = args[args.index("-filter_complex") + 1]
        self.assertIn(expected_overlay, filter_complex)

    def test_zero_offset_is_not_replaced_by_default(self):
        self.assert_top_right_overlay(
            {"offset": 0},
            "[0:v][badge0]overlay=x=W-w-0:y=0:shortest=0[vout]",
        )

    def test_ten_pixel_offset_is_direct_pixel_offset(self):
        self.assert_top_right_overlay(
            {"offset": 10},
            "[0:v][badge0]overlay=x=W-w-10:y=10:shortest=0[vout]",
        )

    def test_missing_offset_uses_default_ten(self):
        self.assertEqual(slice_mod.BADGE_DEFAULT_OFFSET, 10)
        self.assert_top_right_overlay(
            {},
            "[0:v][badge0]overlay=x=W-w-10:y=10:shortest=0[vout]",
        )

    def test_negative_offset_clamps_to_zero(self):
        self.assert_top_right_overlay(
            {"offset": -5},
            "[0:v][badge0]overlay=x=W-w-0:y=0:shortest=0[vout]",
        )

    def test_invalid_offset_uses_default_ten(self):
        self.assert_top_right_overlay(
            {"offset": "not-an-integer"},
            "[0:v][badge0]overlay=x=W-w-10:y=10:shortest=0[vout]",
        )


if __name__ == "__main__":
    unittest.main()
