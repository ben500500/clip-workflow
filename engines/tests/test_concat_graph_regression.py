#!/usr/bin/env python3
"""拼接滤镜图回归测试（concat_segments / build_concat_filtergraph）。

钉住 2026-11-25 给引擎加硬时的三条口径，任何一条被改回去这里就红：

  A. 帧率归一**只在各段帧率真的不一致时**启用。同帧率时加 `fps=` 等于再做一次
     CFR 重采样，会让切片线既有成功产物逐帧变样——这是「不动切片线现网产物」的底线。
  B. 无音轨的段接一条后面追加的 `anullsrc` 输入并按该段时长 `atrim`。
     旧写法裸引用 `[i:a]` 会让整条命令当场失败（Stream map ... matches no streams），
     而 anullsrc 是无限长 source，不剪住 concat 永不收尾。
  C. `faststart` 默认关＝切片线既有产物字节不变；素材库拼接显式传 True。

另有需要真实 ffmpeg 的实证用例（探测准确性、moov 位置），环境缺 ffmpeg 时只跳过
这部分，纯函数用例照样跑（CI/本机都能拿到有意义结果）。

用法：
  python3 engines/tests/test_concat_graph_regression.py
退出码：0=通过 / 1=失败 / 2=模块加载不了（引擎语法错或缺依赖）。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

_ENGINES_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINES_DIR = os.path.dirname(_ENGINES_DIR)
_ENGINE_PATH = os.path.join(_ENGINES_DIR, "slice.py")

RESULTS = []  # (label, ok, detail)


def record(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" · {detail}" if detail else ""))


def load_engine():
    """按文件路径加载引擎（与后端适配层同一种加载方式，顺带证明它可被独立加载）。"""
    spec = importlib.util.spec_from_file_location("clip_engines_slice", _ENGINE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _have(tool):
    return shutil.which(tool) is not None


def _synth(path, w, h, fps, seconds, audio):
    """合成一段测试片：可控分辨率/帧率/时长/有无音轨。"""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"testsrc=size={w}x{h}:rate={fps}:duration={seconds}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        cmd += ["-c:a", "aac", "-b:a", "64k"]
    cmd += ["-t", str(seconds), "-pix_fmt", "yuv420p", path]
    subprocess.run(cmd, check=True, capture_output=True)


# ────────────────────────── 纯函数用例（不需要 ffmpeg） ──────────────────────────

def test_graph_engine(mod):
    build = mod.build_concat_filtergraph

    # A1 同帧率两段：不加 fps 滤镜
    g, silent, notes = build(
        [{"has_audio": True, "duration": 5.0, "fps": 25.0},
         {"has_audio": True, "duration": 3.0, "fps": 25.0}], 720, 1280)
    record("A1 同帧率不加 fps 滤镜", "fps=" not in g, "无 fps=")
    record("A2 同帧率无说明输出", notes == [], f"notes={notes}")
    record("A3 全有声不补静音输入", silent == 0, f"silent_inputs={silent}")
    record("A4 有声段直连 [i:a]", "[0:a]aformat" in g and "[1:a]aformat" in g)
    record("A5 尾部 concat 声明正确", "concat=n=2:v=1:a=1[v][a]" in g)
    record("A6 输入标签与段数一一对应",
           g.count("[v0][a0][v1][a1]") == 1, "拼接标签顺序")

    # final_video_filter：不传/显式 None 保持原图，传入时只改 concat 后的视频尾链。
    graph_specs = [
        {"has_audio": True, "duration": 5.0, "fps": 25.0},
        {"has_audio": True, "duration": 3.0, "fps": 25.0},
    ]
    base_graph = build(graph_specs, 720, 1280)[0]
    none_graph = build(graph_specs, 720, 1280, final_video_filter=None)[0]
    final_filter = "drawtext=text='FIXED'"
    filtered_graph = build(graph_specs, 720, 1280, final_video_filter=final_filter)[0]
    record("A7 显式 None 保持原图字节级形状", none_graph == base_graph)
    record("A8 最终滤镜位于 concat 后且视频独立中继",
           "concat=n=2:v=1:a=1[vconcat][a];[vconcat]" + final_filter + "[v]" in filtered_graph)
    record("A9 最终滤镜不改变音频输出标签",
           filtered_graph.endswith(final_filter + "[v]") and "concat=n=2:v=1:a=1[vconcat][a]" in filtered_graph)

    # B1 混帧率：目标帧率取首段
    g2, s2, n2 = build(
        [{"has_audio": True, "duration": 5.0, "fps": 25.0},
         {"has_audio": True, "duration": 3.0, "fps": 30.0}], 720, 1280)
    record("B1 混帧率启用 fps 归一", ",fps=25[v0]" in g2 and ",fps=25[v1]" in g2,
           "取首段 25 而非末段 30")
    record("B2 混帧率有白话说明", any("帧率不一致" in x for x in n2), f"notes={n2}")

    # C1 第二段无声：静音输入索引 = n + k，且按该段时长 atrim
    g3, s3, n3 = build(
        [{"has_audio": True, "duration": 5.0, "fps": 25.0},
         {"has_audio": False, "duration": 3.4, "fps": 25.0}], 720, 1280)
    record("C1 无声段计数正确", s3 == 1, f"silent_inputs={s3}")
    record("C2 静音输入索引为 len(specs)+k", "[2:a]atrim" in g3, "第二段无声→索引 2")
    record("C3 静音链按该段时长剪住", "atrim=0:3.4" in g3, "不剪住 concat 永不收尾")
    record("C4 无声段不再裸引用 [1:a]", "[1:a]" not in g3)
    record("C5 无声有白话说明", any("无音轨" in x for x in n3), f"notes={n3}")

    # C6 时长探不到时 atrim 下限 0.1（写 0 会得到空轨并让 concat 立刻收尾）
    g4, s4, _ = build(
        [{"has_audio": False, "duration": 0.0, "fps": 0.0},
         {"has_audio": True, "duration": 2.0, "fps": 0.0}], 1080, 1920)
    record("C6 时长缺失时 atrim 兜到 0.1", "atrim=0:0.1" in g4,
           "0 时长会让 concat 直接收尾")
    record("C7 混帧率判据忽略探不到的 0", "fps=" not in g4,
           "0.0 不算一个独立帧率，否则恒判混帧率")

    # D 混合场景：三段、首末有声中间无声、帧率 24/25/24
    g5, s5, n5 = build(
        [{"has_audio": True, "duration": 4.0, "fps": 24.0},
         {"has_audio": False, "duration": 2.0, "fps": 25.0},
         {"has_audio": True, "duration": 3.0, "fps": 24.0}], 720, 1280)
    record("D1 多段无声索引连排", "[3:a]atrim=0:2" in g5 and s5 == 1, f"silent={s5}")
    record("D2 混帧率取首段 24", ",fps=24[v0]" in g5 and ",fps=24[v2]" in g5)
    record("D3 concat n 随段数", "concat=n=3:v=1:a=1" in g5)
    record("D4 几何用传入的 tw/th", "scale=720:1280" in g5 and "pad=720:1280" in g5)
    record("D5 SAR 归一未丢", "setsar=1" in g5)


def test_probe_defaults(mod):
    """探测函数的失败方向：宁可让 ffmpeg 报错，不可把有声悄悄变成无声。"""
    spec = mod._probe_concat_spec("/definitely/not/a/file.mp4")
    record("E1 探不到文件不抛异常", isinstance(spec, dict), json.dumps(spec, ensure_ascii=False))
    record("E2 探测失败按「有音轨」处理", spec.get("has_audio") is True,
           "反向默认会把有声变无声，产物只有耳朵听得出")
    record("E3 探测失败时长/帧率为 0", spec.get("duration") == 0.0 and spec.get("fps") == 0.0,
           f"{spec}")


def test_cmd_shape(mod):
    """拼出来的命令行形状：faststart 是显式开关，copy 快速通道不被新逻辑破坏。"""
    calls = []

    def spy(cmd, timeout=None, threads=1, **kw):
        calls.append(list(cmd))

    real_run, real_probe = mod.run_ffmpeg, mod._probe_concat_spec
    mod.run_ffmpeg = spy
    try:
        # 假路径 → 探测全回默认（有声/0 时长/0 帧率），签名探测失败 → 必走重编码
        mod.concat_segments(["/nope/a.mp4", "/nope/b.mp4"], "/tmp/out_spuriously.mp4")
        record("F1 重编码通道带完整 map", calls and calls[-1][:1] == ["ffmpeg"]
               and "-map" in calls[-1], str(calls[-1][-6:]))
        record("F2 默认不加 -movflags", not any("+faststart" in c for c in calls),
               "faststart 默认关＝切片线既有产物字节不变")

        mod.concat_segments(["/nope/a.mp4", "/nope/b.mp4"], "/tmp/out_spuriously.mp4",
                            faststart=True)
        record("F3 显式传 faststart 才加 -movflags",
               any("+faststart" in c for c in calls[-1]), str(calls[-1][-4:]))

        # 探测到第二段无声 → 命令行里多一条 lavfi 输入
        mod._probe_concat_spec = lambda p: {"has_audio": "/nope/a.mp4" == p,
                                            "duration": 2.0, "fps": 30.0}
        mod.concat_segments(["/nope/a.mp4", "/nope/b.mp4"], "/tmp/out_spuriously.mp4")
        last = calls[-1]
        record("F4 无声段补进 lavfi 输入", last.count("anullsrc=channel_layout=stereo:sample_rate=44100") == 1,
               f"lavfi={last.count('-f')}")
        record("F5 时长一致时不加 fps 滤镜", "fps=" not in " ".join(last))
    finally:
        mod.run_ffmpeg, mod._probe_concat_spec = real_run, real_probe
        for leftover in ("/tmp/out_spuriously.mp4",):
            if os.path.exists(leftover):
                os.unlink(leftover)


def test_text_fusion_cmd_shape(mod):
    """有有效文字时绕过 copy fastpath，concat 与文字只调用一次 ffmpeg。"""
    calls = []
    ass_paths = []
    parts = ["/nope/a.mp4", "/nope/b.mp4"]
    specs = {"has_audio": True, "duration": 2.0, "fps": 30.0}
    final_filter = "drawtext=text='FIXED'"

    def build_text(valid, tw, th, ass_path):
        ass_paths.append(ass_path)
        return final_filter

    def spy(cmd, **kw):
        calls.append(list(cmd))

    with tempfile.TemporaryDirectory() as td, \
         mock.patch.object(mod, "_is_copy_segment", return_value=True), \
         mock.patch.object(mod, "_av_signature", side_effect=AssertionError("不得探测 copy 签名")), \
         mock.patch.object(mod, "_concat_demuxer") as copy_concat, \
         mock.patch.object(mod, "_probe_concat_spec", return_value=specs), \
         mock.patch.object(mod, "ffprobe_resolution", return_value=(720, 1280)), \
         mock.patch.object(mod, "_build_text_overlays_video_filter", side_effect=build_text), \
         mock.patch.object(mod, "apply_text_overlays") as separate_text, \
         mock.patch.object(mod, "run_ffmpeg", side_effect=spy):
        result = mod.concat_segments(
            parts, os.path.join(td, "out.mp4"), threads=3,
            faststart=True, text_overlays=[{"text": "FIXED"}],
        )

    joined = " ".join(calls[0]) if calls else ""
    record("F6 有文字绕过 concat demuxer", not copy_concat.called and "-c copy" not in joined)
    record("F7 融合路径只调用一次 run_ffmpeg", len(calls) == 1 and result == [], f"calls={len(calls)}")
    record("F8 文字滤镜接入硬切 concat 尾部",
           "-map [v] -map [a]" in joined and "[vconcat]" + final_filter + "[v]" in joined)
    record("F9 编码线程/AAC/faststart 保持",
           "-threads 3" in joined and "-c:v libx264" in joined
           and "-c:a aac -b:a 128k" in joined and "+faststart" in joined)
    record("F10 融合成功不再单独叠加且清理 ASS",
           not separate_text.called and len(ass_paths) == 1 and not os.path.exists(ass_paths[0]))


def test_copy_fastpath_untouched(mod):
    """签名一致时仍走 concat demuxer 流拷贝（新逻辑不得把它挤成重编码）。"""
    if not (_have("ffmpeg") and _have("ffprobe")):
        record("G0 缺 ffmpeg，跳过流拷贝实证", True, "SKIP")
        return
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "a.mp4"), os.path.join(td, "b.mp4")
        out = os.path.join(td, "out.mp4")
        for p in (a, b):
            _synth(p, 720, 1280, 25, 2, True)
        calls = []
        real_run = mod.run_ffmpeg

        def spy(cmd, **kw):
            calls.append(list(cmd))
            return real_run(cmd, **kw)  # 真跑：copy 通道拼完还要 ffprobe 校验时长，假产物会被判不符

        mod.run_ffmpeg = spy
        try:
            mod.concat_segments([a, b], out, faststart=True)
        finally:
            mod.run_ffmpeg = real_run
        joined = " ".join(calls[-1]) if calls else ""
        record("G1 同规格仍走 concat demuxer", calls and "concat" in calls[-1]
               and "-f concat" in joined, joined[:120])
        record("G2 流拷贝不重编码", calls and "-c copy" in joined)
        record("G3 流拷贝尊重 faststart 开关", calls and "+faststart" in joined)
        record("G4 流拷贝未被无声/帧率链污染", "anullsrc" not in joined and "fps=" not in joined)


def test_probe_accuracy(mod):
    """真文件上的探测准确性（纯函数用例证不了 has_audio 判据方向）。"""
    if not (_have("ffmpeg") and _have("ffprobe")):
        record("H0 缺 ffmpeg，跳过探测实证", True, "SKIP")
        return
    with tempfile.TemporaryDirectory() as td:
        with_audio = os.path.join(td, "with.mp4")
        silent = os.path.join(td, "silent.mp4")
        odd = os.path.join(td, "odd.mp4")
        _synth(with_audio, 720, 1280, 25, 2, True)
        _synth(silent, 720, 1280, 25, 3, False)
        _synth(odd, 1080, 1920, 30, 2, True)
        sa, sb, sc = (mod._probe_concat_spec(p) for p in (with_audio, silent, odd))
        record("H1 有声段判为有声", sa["has_audio"] is True, str(sa))
        record("H2 无声段判为无声", sb["has_audio"] is False, str(sb))
        record("H3 时长取到实际值", abs(sa["duration"] - 2.0) <= 0.3
               and abs(sb["duration"] - 3.0) <= 0.3, f"{sa['duration']}/{sb['duration']}")
        record("H4 帧率取到实际值", sa["fps"] == 25.0 and sc["fps"] == 30.0,
               f"{sa['fps']}/{sc['fps']}")
        record("H5 30000/1001 与 29.97 判为同帧率",
               mod.build_concat_filtergraph(
                   [{"has_audio": True, "duration": 1.0, "fps": round(30000 / 1001, 3)},
                    {"has_audio": True, "duration": 1.0, "fps": 29.97}], 720, 1280)[0]
               .count("fps=") == 0)


def main():
    if not os.path.exists(_ENGINE_PATH):
        print(f"找不到引擎：{_ENGINE_PATH}")
        return 2
    try:
        mod = load_engine()
    except SystemExit as e:
        print(f"引擎拒绝在本 Python 版本加载（sys.exit {e}）")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"引擎加载失败：{type(e).__name__}: {e}")
        return 2

    test_graph_engine(mod)
    test_probe_defaults(mod)
    test_cmd_shape(mod)
    test_text_fusion_cmd_shape(mod)
    test_copy_fastpath_untouched(mod)
    test_probe_accuracy(mod)

    bad = [r for r in RESULTS if not r[1]]
    total = len(RESULTS)
    skipped = sum(1 for r in RESULTS if r[2] == "SKIP")
    print(f"\n结果：{total - len(bad)}/{total} 通过" + (f"（其中 {skipped} 条因缺依赖跳过）" if skipped else ""))
    if bad:
        print("失败项：")
        for label, _, detail in bad:
            print(f"  - {label} · {detail}")
        return 1
    print("✅ 拼接滤镜图回归全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
