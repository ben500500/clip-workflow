#!/usr/bin/env python3
"""钩子/片尾接缝随机转场回归测试。"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ENGINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _ENGINES_DIR not in sys.path:
    sys.path.insert(0, _ENGINES_DIR)

_SPEC = importlib.util.spec_from_file_location("slice_transition_mod", os.path.join(_ENGINES_DIR, "slice.py"))
_slice = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_slice)


class TransitionSelectionTests(unittest.TestCase):
    def test_scene_score_parser_accepts_old_and_new_keys(self):
        text = "lavfi.scene_score=0.42\nlavfi.scene=0.31\nlavfi.scene_score=bad\n"
        self.assertEqual(_slice._parse_scene_scores(text), [0.42, 0.31])

    def test_tiers_and_fallback(self):
        heavy = _slice._pick_hook_transition(0.60, 30)
        medium = _slice._pick_hook_transition(0.40, 30)
        light = _slice._pick_hook_transition(0.10, 30)
        fallback = _slice._pick_hook_transition(None, 30)
        self.assertIn(heavy["transition"], _slice.HOOK_TRANSITION_TIERS[0][1])
        self.assertIn(medium["transition"], _slice.HOOK_TRANSITION_TIERS[1][1])
        self.assertIn(light["transition"], _slice.HOOK_TRANSITION_TIERS[2][1])
        self.assertIn(fallback["transition"], ("fade", "fadeslow"))
        self.assertEqual(fallback["duration"], 0.2)
        self.assertEqual(_slice._pick_hook_transition(None, 24)["duration"], round(0.2 * 24) / 24)
        self.assertTrue(0.35 <= heavy["duration"] <= 0.50)
        self.assertTrue(0.25 <= medium["duration"] <= 0.35)
        self.assertTrue(0.15 <= light["duration"] <= 0.25)


class TransitionGraphTests(unittest.TestCase):
    def setUp(self):
        self.specs = [
            {"has_audio": True, "duration": 2.0, "fps": 30.0},
            {"has_audio": True, "duration": 3.0, "fps": 30.0},
            {"has_audio": True, "duration": 4.0, "fps": 30.0},
            {"has_audio": False, "duration": 2.0, "fps": 30.0},
        ]
        self.plans = {
            0: {"transition": "dissolve", "duration": 0.30, "scene_score": 0.40},
            2: {"transition": "smoothleft", "duration": 0.40, "scene_score": 0.20},
        }

    def test_only_marked_seams_transition(self):
        graph, silent, notes, applied = _slice.build_transition_concat_filtergraph(
            self.specs, 720, 1280, self.plans
        )
        self.assertEqual(graph.count("xfade="), 2)
        self.assertEqual(graph.count("acrossfade="), 2)
        self.assertEqual(graph.count("concat=n=2:v=1:a=1"), 0)
        self.assertEqual(graph.count("concat=n=2:v=1:a=0"), 1)
        self.assertEqual(graph.count("concat=n=2:v=0:a=1"), 1)
        self.assertIn("offset=1.700000", graph)
        self.assertIn("offset=8.300000", graph)
        self.assertEqual([item["seam"] for item in applied], [0, 2])
        self.assertEqual(silent, 1)
        self.assertIn("[4:a]", graph)
        self.assertTrue(any("外部素材接缝转场" in note for note in notes))

    def test_frame_grid_and_audio_padding(self):
        graph, _, _, _ = _slice.build_transition_concat_filtergraph(
            self.specs, 720, 1280, self.plans
        )
        self.assertEqual(graph.count("fps=30"), 4)
        self.assertEqual(graph.count("settb=AVTB"), 4)
        self.assertEqual(graph.count("apad=whole_dur="), 4)
        self.assertEqual(graph.count("atrim=duration="), 8)

    def test_head_subtitle_offset_uses_transition_start(self):
        applied = [{"seam": 0, "offset": 1.7, "duration": 0.3}]
        self.assertEqual(_slice._head_subtitle_lead_offset(applied, 0, 2.0), 1.7)
        self.assertEqual(_slice._head_subtitle_lead_offset([], 0, 2.0), 2.0)
        self.assertEqual(_slice._head_subtitle_lead_offset(applied, None, 2.0), 0.0)

    def test_video_stream_duration_drives_transition_timeline(self):
        specs = [
            {"has_audio": True, "duration": 1.4, "video_duration": 1.0, "fps": 30.0},
            {"has_audio": True, "duration": 1.4, "video_duration": 1.0, "fps": 30.0},
        ]
        plans = {0: {"transition": "dissolve", "duration": 0.3, "scene_score": 0.4}}
        graph, _, _, applied = _slice.build_transition_concat_filtergraph(specs, 320, 240, plans)
        self.assertIn("offset=0.700000", graph)
        self.assertEqual(graph.count(",trim=duration=1.000000"), 2)
        self.assertEqual(graph.count("atrim=duration=1.000000"), 4)
        self.assertEqual(applied[0]["offset"], 0.7)

    def test_final_video_filter_is_applied_after_transitions(self):
        base_graph, _, _, base_applied = _slice.build_transition_concat_filtergraph(
            self.specs, 720, 1280, self.plans
        )
        none_graph, _, _, _ = _slice.build_transition_concat_filtergraph(
            self.specs, 720, 1280, self.plans, final_video_filter=None
        )
        final_filter = "drawtext=text='FIXED'"
        graph, _, _, applied = _slice.build_transition_concat_filtergraph(
            self.specs, 720, 1280, self.plans, final_video_filter=final_filter
        )
        self.assertEqual(base_graph, none_graph)
        self.assertEqual(applied, base_applied)
        self.assertIn(
            "[vx3]" + final_filter + "[vfinal];[vfinal]null[vout]",
            graph,
        )
        self.assertGreater(graph.index(final_filter), graph.rindex("xfade="))
        self.assertTrue(graph.endswith("[ax3]anull[aout]"))

    def test_short_seam_falls_back_to_hard_cut(self):
        specs = [
            {"has_audio": True, "duration": 0.10, "fps": 30.0},
            {"has_audio": True, "duration": 2.0, "fps": 30.0},
        ]
        plan = {0: {"transition": "dissolve", "duration": 0.30, "scene_score": 0.40}}
        graph, _, notes, applied = _slice.build_transition_concat_filtergraph(
            specs, 720, 1280, plan
        )
        self.assertNotIn("xfade=", graph)
        self.assertEqual(applied, [])
        self.assertTrue(any("保持硬切" in note for note in notes))


class ConcatTransitionCommandTests(unittest.TestCase):
    def setUp(self):
        self.parts = ["/tmp/hook.mp4", "/tmp/body.mp4", "/tmp/outro.mp4"]
        self.specs = [
            {"has_audio": True, "duration": 2.0, "fps": 30.0},
            {"has_audio": True, "duration": 3.0, "fps": 30.0},
            {"has_audio": False, "duration": 2.0, "fps": 30.0},
        ]

    def test_transition_bypasses_copy_fastpath(self):
        calls = []
        with mock.patch.object(_slice, "_is_copy_segment", return_value=True), \
             mock.patch.object(_slice, "_concat_demuxer") as copy_concat, \
             mock.patch.object(_slice, "_probe_concat_spec", side_effect=lambda p: self.specs[self.parts.index(p)]), \
             mock.patch.object(_slice, "ffprobe_resolution", return_value=(720, 1280)), \
             mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
             mock.patch.object(_slice, "_pick_hook_transition", return_value={
                 "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}), \
             mock.patch.object(_slice, "run_ffmpeg", side_effect=lambda cmd, **kw: calls.append(cmd)):
            result = _slice.concat_segments(self.parts, "/tmp/out.mp4", transition_seams=[0, 1])
        copy_concat.assert_not_called()
        self.assertEqual([item["seam"] for item in result], [0, 1])
        self.assertEqual(len(calls), 1)
        joined = " ".join(calls[0])
        self.assertIn("xfade=transition=dissolve", joined)
        self.assertIn("acrossfade=", joined)
        self.assertNotIn("-c copy", joined)

    def test_xfade_failure_retries_with_hard_concat(self):
        calls = []

        def flaky(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:
                raise RuntimeError("xfade failed")

        with mock.patch.object(_slice, "_probe_concat_spec", side_effect=lambda p: self.specs[self.parts.index(p)]), \
             mock.patch.object(_slice, "ffprobe_resolution", return_value=(720, 1280)), \
             mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
             mock.patch.object(_slice, "_pick_hook_transition", return_value={
                 "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}), \
             mock.patch.object(_slice, "run_ffmpeg", side_effect=flaky):
            result = _slice.concat_segments(self.parts, "/tmp/out.mp4", transition_seams=[0])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result, [])
        self.assertIn("xfade=", " ".join(calls[0]))
        self.assertNotIn("xfade=", " ".join(calls[1]))
        self.assertIn("-map [vout] -map [aout]", " ".join(calls[1]))


class TextOverlayFusionTests(unittest.TestCase):
    def setUp(self):
        self.overlays = [{"text": "FIXED", "position": "top-right"}]

    def test_safety_gate_blocks_each_intermediate_pass(self):
        self.assertTrue(_slice._should_fuse_text_overlays(self.overlays))
        blockers = [
            {"subtitle_mask": {"x": 0, "y": 0}},
            {"subtitle": "/tmp/subtitle.srt"},
            {"watermark_mask": {"x": 0, "y": 0}},
            {"badges": [{"path": "/tmp/badge.png"}]},
        ]
        for kwargs in blockers:
            with self.subTest(kwargs=kwargs):
                self.assertFalse(_slice._should_fuse_text_overlays(self.overlays, **kwargs))
        # 预叠角标已完成于源片，不构成 concat→文字之间的新处理。
        self.assertTrue(_slice._should_fuse_text_overlays(
            self.overlays, badges=[{"path": "/tmp/badge.png"}],
            badges_preapplied=True,
        ))
        self.assertFalse(_slice._should_fuse_text_overlays(
            self.overlays, badges=[{"path": "/tmp/badge.png"}],
            badges_preapplied=True, subtitle_mask={"x": 0, "y": 0},
        ))
        # args.cover 在文字之后执行，不是融合门控的阻断项。
        self.assertTrue(_slice._should_fuse_text_overlays(self.overlays))

    def test_safety_gate_requires_valid_text(self):
        for overlays in (None, [], [{}], [{"text": "   "}]):
            with self.subTest(overlays=overlays):
                self.assertFalse(_slice._should_fuse_text_overlays(overlays))

    def test_ass_explicit_size_does_not_probe_source(self):
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "overlays.ass")
            with mock.patch.object(_slice, "ffprobe_size") as probe:
                _slice._build_text_overlays_ass(
                    self.overlays, "/not/a/real/intermediate.mp4", ass_path,
                    width=720, height=1280,
                )
            probe.assert_not_called()
            with open(ass_path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("PlayResX: 720", content)
            self.assertIn("PlayResY: 1280", content)

    def test_video_filter_falls_back_to_drawtext_without_probe(self):
        with tempfile.TemporaryDirectory() as td:
            ass_path = os.path.join(td, "overlays.ass")
            with mock.patch.object(_slice, "_build_text_overlays_ass", side_effect=RuntimeError("ASS failed")), \
                 mock.patch.object(_slice, "_build_text_overlays_filter", return_value="drawtext=text='FIXED'") as fallback, \
                 mock.patch.object(_slice, "ffprobe_size") as probe:
                result = _slice._build_text_overlays_video_filter(
                    self.overlays, 720, 1280, ass_path,
                )
            self.assertEqual(result, "drawtext=text='FIXED'")
            fallback.assert_called_once_with(self.overlays)
            probe.assert_not_called()

    def test_single_segment_applies_text_once_instead_of_move(self):
        with mock.patch.object(_slice, "apply_text_overlays") as apply_text, \
             mock.patch.object(_slice.shutil, "move") as move:
            result = _slice.concat_segments(
                ["/tmp/one.mp4"], "/tmp/out.mp4", text_overlays=self.overlays,
            )
        self.assertEqual(result, [])
        move.assert_not_called()
        apply_text.assert_called_once_with(
            "/tmp/one.mp4", "/tmp/out.mp4", self.overlays,
            threads=1, encoder="libx264",
        )


class ConcatTextCommandTests(unittest.TestCase):
    def setUp(self):
        self.parts = ["/tmp/hook.mp4", "/tmp/body.mp4", "/tmp/outro.mp4"]
        self.specs = [
            {"has_audio": True, "duration": 2.0, "fps": 30.0},
            {"has_audio": True, "duration": 3.0, "fps": 30.0},
            {"has_audio": False, "duration": 2.0, "fps": 30.0},
        ]
        self.overlays = [{"text": "FIXED"}]
        self.final_filter = "drawtext=text='FIXED'"

    def test_transition_and_text_fuse_in_one_encode(self):
        calls = []
        ass_paths = []

        def build_text(valid, tw, th, ass_path):
            ass_paths.append(ass_path)
            return self.final_filter

        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(_slice, "_probe_concat_spec", side_effect=lambda p: self.specs[self.parts.index(p)]), \
             mock.patch.object(_slice, "ffprobe_resolution", return_value=(720, 1280)), \
             mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
             mock.patch.object(_slice, "_pick_hook_transition", return_value={
                 "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}), \
             mock.patch.object(_slice, "_build_text_overlays_video_filter", side_effect=build_text), \
             mock.patch.object(_slice, "apply_text_overlays") as separate_text, \
             mock.patch.object(_slice, "run_ffmpeg", side_effect=lambda cmd, **kw: calls.append(cmd)):
            result = _slice.concat_segments(
                self.parts, os.path.join(td, "out.mp4"), transition_seams=[0],
                text_overlays=self.overlays,
            )

        self.assertEqual([item["seam"] for item in result], [0])
        self.assertEqual(len(calls), 1)
        joined = " ".join(calls[0])
        self.assertIn("xfade=transition=dissolve", joined)
        self.assertIn(self.final_filter + "[vfinal];[vfinal]null[vout]", joined)
        self.assertIn("-map [vout] -map [aout]", joined)
        separate_text.assert_not_called()
        self.assertEqual(len(ass_paths), 1)
        self.assertFalse(os.path.exists(ass_paths[0]))

    def test_transition_failure_retries_hardcut_with_same_text(self):
        calls = []

        def flaky(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:
                raise RuntimeError("xfade failed")

        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(_slice, "_probe_concat_spec", side_effect=lambda p: self.specs[self.parts.index(p)]), \
             mock.patch.object(_slice, "ffprobe_resolution", return_value=(720, 1280)), \
             mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
             mock.patch.object(_slice, "_pick_hook_transition", return_value={
                 "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}), \
             mock.patch.object(_slice, "_build_text_overlays_video_filter", return_value=self.final_filter), \
             mock.patch.object(_slice, "apply_text_overlays") as separate_text, \
             mock.patch.object(_slice, "run_ffmpeg", side_effect=flaky):
            result = _slice.concat_segments(
                self.parts, os.path.join(td, "out.mp4"), transition_seams=[0],
                text_overlays=self.overlays,
            )

        self.assertEqual(result, [])
        self.assertEqual(len(calls), 2)
        self.assertIn("xfade=", " ".join(calls[0]))
        self.assertNotIn("xfade=", " ".join(calls[1]))
        self.assertIn(self.final_filter, " ".join(calls[0]))
        self.assertIn(self.final_filter, " ".join(calls[1]))
        separate_text.assert_not_called()

    def test_all_fused_attempts_fail_uses_separate_text_fallback(self):
        calls = []
        ass_paths = []

        def build_text(valid, tw, th, ass_path):
            ass_paths.append(ass_path)
            return self.final_filter

        def flaky(cmd, **kw):
            calls.append(cmd)
            if len(calls) <= 2:
                raise RuntimeError("fused render failed")

        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out.mp4")
            with mock.patch.object(_slice, "_probe_concat_spec", side_effect=lambda p: self.specs[self.parts.index(p)]), \
                 mock.patch.object(_slice, "ffprobe_resolution", return_value=(720, 1280)), \
                 mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
                 mock.patch.object(_slice, "_pick_hook_transition", return_value={
                     "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}), \
                 mock.patch.object(_slice, "_build_text_overlays_video_filter", side_effect=build_text), \
                 mock.patch.object(_slice, "apply_text_overlays") as separate_text, \
                 mock.patch.object(_slice.os, "replace") as replace, \
                 mock.patch.object(_slice, "run_ffmpeg", side_effect=flaky):
                result = _slice.concat_segments(
                    self.parts, out, transition_seams=[0], text_overlays=self.overlays,
                )

            self.assertEqual(result, [])
            self.assertEqual(len(calls), 3)
            self.assertIn(self.final_filter, " ".join(calls[0]))
            self.assertIn(self.final_filter, " ".join(calls[1]))
            self.assertNotIn(self.final_filter, " ".join(calls[2]))
            self.assertNotIn("xfade=", " ".join(calls[2]))
            text_out = out + ".textov.mp4"
            separate_text.assert_called_once_with(
                out, text_out, self.overlays, threads=1, encoder="libx264",
            )
            replace.assert_called_once_with(text_out, out)
            self.assertEqual(len(ass_paths), 1)
            self.assertFalse(os.path.exists(ass_paths[0]))

    def test_text_filter_build_failure_uses_hardcut_then_separate(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out.mp4")
            with mock.patch.object(_slice, "_probe_concat_spec", side_effect=lambda p: self.specs[self.parts.index(p)]), \
                 mock.patch.object(_slice, "ffprobe_resolution", return_value=(720, 1280)), \
                 mock.patch.object(_slice, "_hook_seam_score") as seam_score, \
                 mock.patch.object(_slice, "_build_text_overlays_video_filter", return_value=""), \
                 mock.patch.object(_slice, "apply_text_overlays") as separate_text, \
                 mock.patch.object(_slice.os, "replace") as replace, \
                 mock.patch.object(_slice, "run_ffmpeg", side_effect=lambda cmd, **kw: calls.append(cmd)):
                result = _slice.concat_segments(
                    self.parts, out, transition_seams=[0], text_overlays=self.overlays,
                )
            self.assertEqual(result, [])
            self.assertEqual(len(calls), 1)
            self.assertNotIn("xfade=", " ".join(calls[0]))
            seam_score.assert_not_called()
            separate_text.assert_called_once()
            replace.assert_called_once_with(out + ".textov.mp4", out)

    def test_text_filter_failure_never_retries_without_text(self):
        calls = []

        def flaky(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:
                raise RuntimeError("hardcut failed")

        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out.mp4")
            with mock.patch.object(_slice, "_probe_concat_spec", side_effect=lambda p: self.specs[self.parts.index(p)]), \
                 mock.patch.object(_slice, "ffprobe_resolution", return_value=(720, 1280)), \
                 mock.patch.object(_slice, "_hook_seam_score") as seam_score, \
                 mock.patch.object(_slice, "_build_text_overlays_video_filter", return_value=""), \
                 mock.patch.object(_slice, "apply_text_overlays") as separate_text, \
                 mock.patch.object(_slice.os, "replace") as replace, \
                 mock.patch.object(_slice, "run_ffmpeg", side_effect=flaky):
                result = _slice.concat_segments(
                    self.parts, out, transition_seams=[0], text_overlays=self.overlays,
                )
            self.assertEqual(result, [])
            self.assertEqual(len(calls), 2)
            # 唯一 concat 尝试失败后必须直接走带文字的两遍兜底；
            # 重试可以再拼一次，但成功后只能经 separate-text 返回成品。
            separate_text.assert_called_once_with(
                out, out + ".textov.mp4", self.overlays, threads=1, encoder="libx264",
            )
            replace.assert_called_once_with(out + ".textov.mp4", out)
            seam_score.assert_not_called()


def _ffmpeg_has_filter(name):
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return any(
        name in line.split()[:2]
        for line in (proc.stdout or "").splitlines()
    )


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "缺少 ffmpeg/ffprobe")
class TransitionE2ETests(unittest.TestCase):
    @staticmethod
    def _synth(path, seconds, audio=True):
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"testsrc2=size=320x240:rate=30:duration={seconds}",
        ]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
        cmd += ["-t", str(seconds), "-pix_fmt", "yuv420p", path]
        subprocess.run(cmd, check=True, capture_output=True)

    @staticmethod
    def _probe(path):
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,duration,width,height,r_frame_rate",
            "-of", "json", path,
        ], text=True)
        return json.loads(raw)

    def test_hook_body_and_silent_outro(self):
        with tempfile.TemporaryDirectory() as td:
            hook, body, outro = [os.path.join(td, name) for name in ("hook.mp4", "body.mp4", "outro.mp4")]
            out = os.path.join(td, "out.mp4")
            self._synth(hook, 2.0)
            self._synth(body, 2.0)
            self._synth(outro, 2.0, audio=False)
            with mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
                 mock.patch.object(_slice, "_pick_hook_transition", return_value={
                     "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}):
                _slice.concat_segments([hook, body, outro], out, transition_seams=[0, 1])
            meta = self._probe(out)
            duration = float(meta["format"]["duration"])
            self.assertAlmostEqual(duration, 5.4, delta=0.08)
            streams = meta["streams"]
            self.assertTrue(any(s.get("codec_type") == "video" for s in streams))
            self.assertTrue(any(s.get("codec_type") == "audio" for s in streams))
            decoded = subprocess.run([
                "ffmpeg", "-v", "error", "-i", out, "-f", "null", "-"
            ], capture_output=True, text=True)
            self.assertEqual(decoded.returncode, 0, decoded.stderr)


    @unittest.skipUnless(_ffmpeg_has_filter("ass"), "本地 ffmpeg 缺 libass（ass 滤镜）")
    def test_transition_and_fixed_text_use_one_encode(self):
        with tempfile.TemporaryDirectory() as td:
            parts = [os.path.join(td, name) for name in ("a.mp4", "b.mp4")]
            out = os.path.join(td, "out.mp4")
            for path in parts:
                self._synth(path, 1.0)
            real_run = _slice.run_ffmpeg
            with mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
                 mock.patch.object(_slice, "_pick_hook_transition", return_value={
                     "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}), \
                 mock.patch.object(_slice, "run_ffmpeg", side_effect=real_run) as run:
                applied = _slice.concat_segments(
                    parts, out, transition_seams=[0],
                    text_overlays=[{"text": "FIXED"}],
                )
            self.assertEqual([item["seam"] for item in applied], [0])
            self.assertEqual(run.call_count, 1)
            cmd = run.call_args.args[0]
            graph = cmd[cmd.index("-filter_complex") + 1]
            self.assertIn("xfade=transition=dissolve", graph)
            self.assertIn("ass=", graph)
            meta = self._probe(out)
            self.assertAlmostEqual(float(meta["format"]["duration"]), 1.7, delta=0.08)
            decoded = subprocess.run([
                "ffmpeg", "-v", "error", "-i", out, "-f", "null", "-"
            ], capture_output=True, text=True)
            self.assertEqual(decoded.returncode, 0, decoded.stderr)

    def test_long_audio_does_not_push_xfade_past_video_end(self):
        with tempfile.TemporaryDirectory() as td:
            parts = [os.path.join(td, name) for name in ("a.mp4", "b.mp4")]
            out = os.path.join(td, "out.mp4")
            for path in parts:
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=30:duration=1", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1.4", "-c:v", "libx264", "-c:a", "aac",
                    "-pix_fmt", "yuv420p", path,
                ], check=True, capture_output=True)
            with mock.patch.object(_slice, "_hook_seam_score", return_value=0.40), \
                 mock.patch.object(_slice, "_pick_hook_transition", return_value={
                     "transition": "dissolve", "duration": 0.30, "scene_score": 0.40}):
                _slice.concat_segments(parts, out, transition_seams=[0])
            streams = self._probe(out)["streams"]
            video = next(s for s in streams if s["codec_type"] == "video")
            audio = next(s for s in streams if s["codec_type"] == "audio")
            self.assertAlmostEqual(float(video["duration"]), 1.7, delta=0.08)
            self.assertAlmostEqual(float(audio["duration"]), 1.7, delta=0.08)


if __name__ == "__main__":
    unittest.main(verbosity=2)
