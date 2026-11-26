#!/usr/bin/env python3
"""AAC 负预滚检测与 warning-only 拼接回归测试。"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
from unittest import mock

_ENGINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _ENGINES_DIR not in sys.path:
    sys.path.insert(0, _ENGINES_DIR)

_SPEC = importlib.util.spec_from_file_location("slice_mod", os.path.join(_ENGINES_DIR, "slice.py"))
_slice = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_slice)


def _probe_result(codec="aac", sample_rate=44100, pts="-0.023220", skip_samples=1024):
    return {
        "streams": [{"codec_name": codec, "sample_rate": sample_rate}],
        "packets": [{
            "pts_time": pts,
            "side_data_list": [{"skip_samples": skip_samples}],
        }],
    }


class AacPrerollDetectionTests(unittest.TestCase):
    def test_normal_one_frame_priming_is_safe(self):
        with mock.patch.object(_slice.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(_probe_result()), stderr="")
            self.assertIsNone(_slice._detect_aac_preroll("normal.mp4"))

    def test_excessive_skip_samples_is_risk(self):
        payload = _probe_result(pts="-1.009048", skip_samples=44499)
        with mock.patch.object(_slice.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
            result = _slice._detect_aac_preroll("body.mp4")
        self.assertEqual(result["status"], "risk")
        self.assertEqual(result["skip_samples"], 44499)
        self.assertEqual(result["pts_time"], -1.009048)

    def test_negative_pts_without_side_data_is_risk(self):
        payload = _probe_result(pts="-1.009048", skip_samples=0)
        payload["packets"][0].pop("side_data_list")
        with mock.patch.object(_slice.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
            self.assertEqual(_slice._detect_aac_preroll("body.mp4")["status"], "risk")

    def test_non_aac_is_not_risk(self):
        with mock.patch.object(_slice.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(_probe_result(codec="mp3")), stderr="")
            self.assertIsNone(_slice._detect_aac_preroll("clip.mp4"))

    def test_aac_without_readable_packet_is_unknown(self):
        payload = {"streams": [{"codec_name": "aac", "sample_rate": 44100}], "packets": []}
        with mock.patch.object(_slice.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
            self.assertEqual(_slice._detect_aac_preroll("clip.mp4")["status"], "unknown")

    def test_skip_sample_boundary(self):
        for skip_samples, expected in ((1024, None), (1025, "risk")):
            payload = _probe_result(pts="0", skip_samples=skip_samples)
            with self.subTest(skip_samples=skip_samples), mock.patch.object(_slice.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
                result = _slice._detect_aac_preroll("clip.mp4")
                self.assertEqual(result and result.get("status"), expected)

    def test_timeout_and_invalid_json_are_unknown(self):
        with mock.patch.object(_slice.subprocess, "run", side_effect=TimeoutError("timed out")):
            self.assertEqual(_slice._detect_aac_preroll("clip.mp4")["status"], "unknown")
        with mock.patch.object(_slice.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="not-json", stderr="")
            self.assertEqual(_slice._detect_aac_preroll("clip.mp4")["status"], "unknown")

    def test_probe_failure_is_unknown_not_safe(self):
        with mock.patch.object(_slice.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="broken file")
            result = _slice._detect_aac_preroll("broken.mp4")
        self.assertEqual(result["status"], "unknown")
        self.assertIn("broken file", result["error"])

    def test_copy_concat_warns_but_does_not_reencode(self):
        parts = ["hook.mp4", "body.mp4", "outro.mp4"]
        risk = {"status": "risk", "pts_time": -1.009048, "skip_samples": 44499,
                "sample_rate": 44100, "normal_preroll_seconds": 0.02322}
        stderr = io.StringIO()
        with mock.patch.object(_slice, "_is_copy_segment", return_value=True), \
                mock.patch.object(_slice, "_av_signature", return_value=("same",)), \
                mock.patch.object(_slice, "_detect_aac_preroll", side_effect=[None, risk, None]), \
                mock.patch.object(_slice, "_concat_demuxer") as concat, \
                mock.patch.object(_slice, "ffprobe_duration", side_effect=[3.0, 160.0, 3.0, 166.0]), \
                mock.patch.object(_slice, "run_ffmpeg") as reencode, \
                contextlib.redirect_stderr(stderr):
            _slice.concat_segments(parts, "out.mp4", copy_if_possible=True)
        concat.assert_called_once_with(parts, "out.mp4")
        reencode.assert_not_called()
        self.assertIn("WARNING AAC_PREROLL_RISK out=out.mp4 segment=1", stderr.getvalue())
        self.assertIn("out=out.mp4", stderr.getvalue())
        self.assertIn("part=body.mp4", stderr.getvalue())
        self.assertIn("仍按当前策略流拷贝拼接", stderr.getvalue())


    def test_probe_failure_does_not_block_copy_concat(self):
        parts = ["hook.mp4", "body.mp4"]
        stderr = io.StringIO()
        with mock.patch.object(_slice, "_is_copy_segment", return_value=True), \
                mock.patch.object(_slice, "_av_signature", return_value=("same",)), \
                mock.patch.object(_slice, "_detect_aac_preroll", return_value={"status": "unknown", "error": "timeout"}), \
                mock.patch.object(_slice, "_concat_demuxer") as concat, \
                mock.patch.object(_slice, "ffprobe_duration", side_effect=[3.0, 160.0, 163.0]), \
                mock.patch.object(_slice, "run_ffmpeg") as reencode, \
                contextlib.redirect_stderr(stderr):
            _slice.concat_segments(parts, "out.mp4", copy_if_possible=True)
        concat.assert_called_once_with(parts, "out.mp4")
        reencode.assert_not_called()
        self.assertIn("WARNING AAC_PREROLL_CHECK_FAILED", stderr.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
