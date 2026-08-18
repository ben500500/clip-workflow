"""视频指纹服务（圆桌定稿 Phase 1 核心：L3 音频 + L4 时域盲区覆盖）。

职责：
- compute_visual_fingerprint(path)：画面感知哈希（pHash，DCT 64bit 十六进制）。
- compute_audio_fingerprint(path)：音频声纹（频谱/能量特征签名），覆盖平台 L3 音频指纹盲区。
- compute_segment_fingerprint(path)：时域序列指纹（场景切分签名），覆盖 L4 序列比对盲区。
- compare_fingerprints(a, b)：双指纹距离量化（phash 汉明距离 + 音频距离）。
- 全部依赖 ffmpeg/ffprobe + 可选 numpy/cv2；numpy/cv2 不可用时优雅降级（ffprobe 元数据指纹）。

设计：指纹服务只产出"可比较的距离度量"，落库由 variant_service 负责。
多路指纹（phash / audio / seq）各自归一化到 0~1，合并为综合距离，
供变体生成撞车检测与前端矩阵看板使用。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:  # pragma: no cover
    np = None
    _HAS_NUMPY = False

try:
    import cv2
    _HAS_CV2 = True
except Exception:  # pragma: no cover
    cv2 = None
    _HAS_CV2 = False

# 默认距离阈值（0~1，越大越安全）：综合指纹距离 < 0.15 判定为撞车（高度相似）
DEFAULT_PHASH_THRESHOLD = 0.20    # 画面 pHash 汉明距离占比阈值
DEFAULT_AUDIO_THRESHOLD = 0.15    # 音频指纹距离阈值
DEFAULT_SEG_THRESHOLD = 0.30      # 时域序列距离阈值
# 综合加权（画面为主，音频与时序为辅）
_W_PHASH = 0.5
_W_AUDIO = 0.3
_W_SEG = 0.2


# ─────────────────────────────────────────────────────────────────────
# 基础工具
# ─────────────────────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 60) -> bytes:
    """执行外部命令并返回 stdout。"""
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.decode(errors='replace')[:500]}"
        )
    return proc.stdout


def _probe_duration(path: str) -> float:
    """ffprobe 获取时长（秒）。"""
    try:
        out = _run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ])
        return float(out.decode().strip() or 0)
    except Exception:
        return 0.0


def _probe_resolution(path: str) -> str:
    try:
        out = _run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0", path,
        ])
        return out.decode().strip()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────
# 画面感知哈希（pHash，64bit DCT）
# ─────────────────────────────────────────────────────────────────────
def _extract_sample_frames(path: str, count: int = 8) -> list:
    """抽取 count 个均匀采样帧，返回灰度小图（numpy 数组）或 None 列表。"""
    if not (_HAS_NUMPY and _HAS_CV2):
        return []
    dur = _probe_duration(path)
    if dur <= 0:
        dur = 10.0
    frames: list = []
    for i in range(count):
        t = (dur * (i + 0.5)) / count
        tmp = _read_frame_rgb(path, t)
        if tmp is not None:
            frames.append(tmp)
    return frames


def _read_frame_rgb(path: str, t: float, size: int = 32):
    """用 ffmpeg 抽一帧，经 cv2 解码为灰度小图。"""
    try:
        proc = subprocess.Popen(
            [
                "ffmpeg", "-ss", f"{t:.3f}", "-i", path,
                "-frames:v", "1", "-vf", f"scale={size}:{size}",
                "-f", "image2pipe", "-vcodec", "bmp", "-",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        raw, _ = proc.communicate(timeout=30)
        if not raw:
            return None
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        if img.shape[0] != size or img.shape[1] != size:
            img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
        return img
    except Exception:
        return None


def _dct2(a: np.ndarray):
    """二维 DCT（可分离，手工实现避免依赖 scipy）。返回同尺寸 DCT 系数。"""
    n = a.shape[0]
    if not _HAS_NUMPY:
        return a
    aa = np.asarray(a, dtype=np.float64)
    # 构造正交归一化 DCT-II 基矩阵
    k = np.arange(n)[:, None]
    n_idx = np.arange(n)[None, :]
    coef = np.cos(np.pi * (2 * n_idx + 1) * k / (2 * n))
    coef[0] *= np.sqrt(1.0 / n)
    coef[1:] *= np.sqrt(2.0 / n)
    temp = coef @ aa @ coef.T
    return temp


def _phash_of_gray(img) -> Optional[str]:
    """对灰度图计算 64bit pHash（DCT 低频均值二值化），返回十六进制串。"""
    if not _HAS_NUMPY or img is None:
        return None
    size = 32
    if img.shape[0] != size or img.shape[1] != size:
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    img = img.astype(np.float64) / 255.0
    # 取 8x8 低频（含 DC），共 64 个系数 → 64bit
    dct = _dct2(img)[:8, :8]
    dct = np.asarray(dct, dtype=np.float64)
    # 用中位数二值化（DC 通常显著偏大，但含在序列里作为整体，不影响相对比较）
    med = np.median(dct)
    bits = (dct > med).astype(np.uint8).flatten()
    # 64bit → 16 hex
    hex_str = ""
    for i in range(0, 64, 4):
        v = 0
        for j in range(4):
            v = (v << 1) | int(bits[i + j])
        hex_str += format(v, "x")
    return hex_str


def compute_visual_fingerprint(path: str) -> dict:
    """计算画面 pHash 指纹。

    返回 {algorithm, hash_value, vector, duration, resolution}；
    hash_value 为 16 位十六进制（64bit），vector 为逗号分隔的二值浮点（pgvector 友好）。
    """
    frames = _extract_sample_frames(path, count=8)
    if not frames:
        # 降级：基于文件字节的稳定指纹（无法比对视觉相似，但至少可做精确去重）
        try:
            digest = hashlib.md5(open(path, "rb").read(4 * 1024 * 1024)).hexdigest()
            return {
                "algorithm": "phash_v1",
                "hash_value": digest[:16],
                "vector": None,
                "duration": _probe_duration(path),
                "resolution": _probe_resolution(path),
            }
        except Exception:
            return {"algorithm": "phash_v1", "hash_value": None, "vector": None,
                    "duration": _probe_duration(path), "resolution": _probe_resolution(path)}

    # 各采样帧 pHash，取多数平均（多数投票），作为整片指纹
    hashes = [h for h in (_phash_of_gray(f) for f in frames) if h]
    if not hashes:
        return {"algorithm": "phash_v1", "hash_value": None, "vector": None,
                "duration": _probe_duration(path), "resolution": _probe_resolution(path)}
    # 按 16 进制逐 bit 投票
    hex_len = len(hashes[0])
    final_hex = []
    for bit_pos in range(hex_len * 4):
        ones = 0
        for h in hashes:
            ch = h[bit_pos // 4]
            bit = (int(ch, 16) >> (3 - (bit_pos % 4))) & 1
            ones += bit
        final_hex.append("1" if ones * 2 >= len(hashes) else "0")
    bits_str = "".join(final_hex)
    hex_str = format(int(bits_str, 2), "0%dx" % hex_len)
    # 向量：逗号分隔浮点（0/1）
    vector = ",".join(bits_str)
    return {
        "algorithm": "phash_v1",
        "hash_value": hex_str,
        "vector": vector,
        "duration": _probe_duration(path),
        "resolution": _probe_resolution(path),
    }


# ─────────────────────────────────────────────────────────────────────
# 音频声纹（L3 盲区）
# ─────────────────────────────────────────────────────────────────────
def compute_audio_fingerprint(path: str) -> dict:
    """计算音频指纹：基于帧能量谱的稳定签名。

    用 ffmpeg 把音频降采样为 16k 单声道 PCM，然后按时间窗统计
    RMS/过零率等能量特征序列，经归一化量化得到 64bit 签名。
    覆盖平台 L3 音频指纹比对（变速会同步改音频，故音轨指纹需与画面一起改动）。
    """
    try:
        raw = _run([
            "ffmpeg", "-v", "error", "-i", path, "-vn",
            "-ac", "1", "-ar", "16000", "-f", "s16le", "-acodec", "pcm_s16le", "-",
        ], timeout=120)
    except Exception as e:
        logger.warning("audio extract failed: %s", e)
        return {"algorithm": "audio_v1", "hash_value": None, "vector": None,
                "duration": _probe_duration(path), "resolution": None}
    if not raw:
        return {"algorithm": "audio_v1", "hash_value": None, "vector": None,
                "duration": _probe_duration(path), "resolution": None}
    if _HAS_NUMPY:
        try:
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
            return _audio_signature(samples, _probe_duration(path))
        except Exception as e:
            logger.warning("audio numpy sig failed: %s", e)
    # 降级：音频字节哈希
    digest = hashlib.md5(raw[:4 * 1024 * 1024]).hexdigest()
    return {"algorithm": "audio_v1", "hash_value": digest[:16], "vector": None,
            "duration": _probe_duration(path), "resolution": None}


def _audio_signature(samples: np.ndarray, dur: float) -> dict:
    """把音频样本量化为 384bit 声纹签名（L3 盲区覆盖，对全局变化高灵敏）。

    早期版本用"中位数二值化"（每特征相对自身中位数取方向位），它对**全局均匀
    改变**（如整体音量增益 volume、整体均衡 EQ）不敏感——因为所有窗口同比变化时
    中位数也同向移动，方向位不变，实测 volume=1.12 在 64bit 里 0 位翻转。

    增强版改用**混合量化**，从两个互补维度编码：
      1. 绝对响度分贝档（每窗 RMS→dB 落在固定绝对档位，2bit/窗，取完整档位的低
         2 位二进制）：对全局音量 / 动态变化高度敏感（音量一变，各窗 dB 档整体平移，
         低位翻转大量位）；
      2. 频谱形状多级量化（每窗频谱质心 centroid + 平坦度 flatness 相对全局均值的
         4 级量化，2bit×2/窗）：对 EQ 均衡、变速音调等频谱形状变化敏感。

    采用 64 个时间窗（而非早期 16 窗）以提升时域分辨率，任何窗口级的音量 / 频谱
    细微变化都更容易在某些窗翻转 bit。合计 64 窗 × (2bit + 4bit) = 384bit，对
    volume / EQ / pitch / tempo 等去重手段都能产生足够大的指纹距离，不再把
    "只改音频"的变体误判为撞车。numpy 不可用时仍回退为字节哈希。
    """
    win = 2048
    n_windows = 64
    total = len(samples)
    if total == 0:
        return {"algorithm": "audio_v1", "hash_value": None, "vector": None,
                "duration": dur, "resolution": None}
    step = max(1, total // n_windows)
    dbs = []   # 每窗绝对响度分贝
    cents = []  # 每窗频谱质心
    flats = []  # 每窗频谱平坦度
    for i in range(0, total, step)[:n_windows]:
        seg = samples[i:i + win]
        if len(seg) < 8:
            dbs.append(-100.0); cents.append(0.0); flats.append(0.0)
            continue
        rms = float(np.sqrt(np.mean(seg ** 2)))
        # 绝对响度分贝：对全局音量变化高度敏感（音量变大→档位整体上移→低位翻转）
        dbs.append(20.0 * math.log10(max(rms, 1e-7)))
        mag = np.abs(np.fft.rfft(seg))
        freqs = np.arange(len(mag), dtype=np.float64)
        if mag.sum() > 1e-9:
            cents.append(float((freqs * mag).sum() / mag.sum()))
        else:
            cents.append(0.0)
        if mag.size > 0 and mag.sum() > 1e-9:
            log_mag = np.log(mag + 1e-12)
            flats.append(float(np.exp(np.mean(log_mag)) / (np.mean(mag) + 1e-12)))
        else:
            flats.append(0.0)
    db_arr = np.asarray(dbs, dtype=np.float64)
    cent_arr = np.asarray(cents, dtype=np.float64)
    flat_arr = np.asarray(flats, dtype=np.float64)

    bits: list[str] = []
    # ── 第 1 部分（128bit）：绝对响度分贝档，每窗 2bit（档 0~15，每档 4dB）──
    # 取完整档位（0~15）二进制的低 2 位：任意小幅档位变化都容易翻转低位。
    for db in db_arr:
        level = int(np.clip(round((db + 72.0) / 4.0), 0, 15))
        bits.extend(format(level & 0x03, "02b"))
    # ── 第 2 部分（256bit）：频谱形状多级量化，每窗 4bit（质心 2bit + 平坦度 2bit）──
    # 相对全局均值的 4 级量化，对 EQ / 变速音调造成的频谱形状变化比方向位更敏感。
    c_mean = np.mean(cent_arr)
    c_std = np.std(cent_arr) + 1e-9
    f_mean = np.mean(flat_arr)
    f_std = np.std(flat_arr) + 1e-9
    for c, f in zip(cent_arr, flat_arr):
        c_z = (c - c_mean) / c_std
        c_lvl = int(np.clip(round(c_z * 1.5) + 2, 0, 3))
        f_z = (f - f_mean) / f_std
        f_lvl = int(np.clip(round(f_z * 1.5) + 2, 0, 3))
        bits.extend(format(c_lvl, "02b"))
        bits.extend(format(f_lvl, "02b"))
    bits_str = "".join(bits)  # 384 bits
    hex_str = format(int(bits_str, 2), "096x")
    return {
        "algorithm": "audio_v1",
        "hash_value": hex_str,
        "vector": ",".join(bits_str),
        "duration": dur,
        "resolution": None,
    }


# ─────────────────────────────────────────────────────────────────────
# 时域序列指纹（L4 盲区）
# ─────────────────────────────────────────────────────────────────────
def compute_segment_fingerprint(path: str) -> dict:
    """计算时域序列指纹：场景切分签名。

    用 ffmpeg select='gt(scene,0.4)' 检测场景切换点，得到时间序列，
    对其做量化签名，用于 L4「多帧时间序列匹配」比对（同素材不同切法会被识别）。
    """
    try:
        out = _run([
            "ffmpeg", "-v", "error", "-i", path,
            "-vf", "select='gt(scene,0.4)',showinfo",
            "-f", "null", "-",
        ], timeout=120)
    except Exception as e:
        logger.warning("segment extract failed: %s", e)
        return {"algorithm": "seq_v1", "hash_value": None, "vector": None,
                "duration": _probe_duration(path), "resolution": None}
    times = []
    for line in out.decode(errors="replace").splitlines():
        if "pts_time:" not in line:
            continue
        try:
            pts = float(line.split("pts_time:")[1].split()[0])
            times.append(pts)
        except (ValueError, IndexError):
            continue
    if not times:
        return {"algorithm": "seq_v1", "hash_value": None, "vector": None,
                "duration": _probe_duration(path), "resolution": None}
    # 量化场景切换时刻 → 64bit 签名（按相对时间 0~1 分桶）
    dur = _probe_duration(path) or 1.0
    buckets = [0] * 64
    for t in times:
        idx = min(63, int((t / dur) * 64))
        buckets[idx] = 1
    bits_str = "".join(str(b) for b in buckets)
    hex_str = format(int(bits_str, 2), "016x")
    return {
        "algorithm": "seq_v1",
        "hash_value": hex_str,
        "vector": ",".join(bits_str),
        "duration": dur,
        "resolution": None,
    }


# ─────────────────────────────────────────────────────────────────────
# 指纹比对 / 撞车判定
# ─────────────────────────────────────────────────────────────────────
def hamming_distance_hex(a: str, b: str) -> float:
    """两个十六进制指纹的归一化汉明距离（0~1）。"""
    if not a or not b:
        return 1.0  # 无法比较视为差异大
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    n = 0
    for i in range(min(len(a), len(b))):
        x = int(a[i], 16) ^ int(b[i], 16)
        n += bin(x).count("1")
    # 未覆盖的高位视为不同
    n += (max_len - min(len(a), len(b))) * 4
    return n / (max_len * 4.0)


def vector_distance(a: Optional[str], b: Optional[str]) -> float:
    """两个逗号分隔 0/1 向量的归一化汉明距离（0~1）。"""
    if not a or not b:
        return 1.0
    av = a.split(",")
    bv = b.split(",")
    m = min(len(av), len(bv))
    if m == 0:
        return 1.0
    diff = sum(1 for i in range(m) if av[i] != bv[i])
    diff += abs(len(av) - len(bv))
    return diff / max(len(av), len(bv), 1)


_ALGO_KEY = {
    "phash_v1": ("phash", "phash_vector"),
    "audio_v1": ("audio_hash", "audio_vector"),
    "seq_v1": ("seg_hash", "seg_vector"),
}


def _extract_algo(fp_dict: dict, algo: str):
    """从指纹字典中提取指定算法的 (hash, vector)。

    兼容两种输入结构：
      1. compute_full_fingerprint 的输出：{phash, phash_vector, audio_hash,
         audio_vector, seg_hash, seg_vector, ...}（不含 algorithm 字段）；
      2. 单算法 DB 记录：{algorithm, hash_value, vector}。
    返回 (hash, vector)，缺失返回 (None, None)。
    """
    if fp_dict.get("algorithm") == algo:
        return fp_dict.get("hash_value"), fp_dict.get("vector")
    # 若字典带 algorithm 但不是目标算法，说明是另一路指纹，无法用于本路比较
    if fp_dict.get("algorithm"):
        return None, None
    key = _ALGO_KEY.get(algo)
    if not key:
        return None, None
    return fp_dict.get(key[0]), fp_dict.get(key[1])


def _algo_distance(fa: dict, fb: dict, algo: str) -> float:
    """比较两组指纹在指定算法上的距离（0~1）。缺失视为 1.0。"""
    ha, va = _extract_algo(fa, algo)
    hb, vb = _extract_algo(fb, algo)
    if not ha or not hb:
        return 1.0
    # 画面类（phash）优先用向量距离（对尺寸变化更鲁棒）
    if algo == "phash_v1" and va and vb:
        return vector_distance(va, vb)
    return hamming_distance_hex(ha, hb)


def compare_fingerprints(fa: dict, fb: dict) -> dict:
    """比较两组指纹，返回多路距离 + 综合距离。

    返回 {phash_distance, audio_distance, seg_distance, combined_distance}，
    各距离 0~1（0=完全相同，1=完全不同）。

    兼容两种输入结构：compute_full_fingerprint 的全量输出，或单算法 DB 记录
    {algorithm, hash_value, vector}；同路指纹缺失时该路距离记为 1.0。
    """
    phash_d = _algo_distance(fa, fb, "phash_v1")
    audio_d = _algo_distance(fa, fb, "audio_v1")
    seg_d = _algo_distance(fa, fb, "seq_v1")
    combined = (_W_PHASH * phash_d) + (_W_AUDIO * audio_d) + (_W_SEG * seg_d)
    return {
        "phash_distance": round(phash_d, 4),
        "audio_distance": round(audio_d, 4),
        "seg_distance": round(seg_d, 4),
        "combined_distance": round(combined, 4),
    }


def is_collision(distances: dict, thresholds: Optional[dict] = None) -> tuple[bool, str]:
    """判定是否撞车。

    thresholds 支持 {phash, audio, seg, combined} 覆盖默认阈值（0~1）。
    任一路低于对应阈值即判定高度相似（撞车）。
    """
    t = thresholds or {}
    phash_t = t.get("phash", DEFAULT_PHASH_THRESHOLD)
    audio_t = t.get("audio", DEFAULT_AUDIO_THRESHOLD)
    seg_t = t.get("seg", DEFAULT_SEG_THRESHOLD)
    comb_t = t.get("combined", 0.15)
    reasons = []
    if distances.get("phash_distance", 1.0) < phash_t:
        reasons.append(f"画面指纹过近({distances['phash_distance']}<{phash_t})")
    if distances.get("audio_distance", 1.0) < audio_t:
        reasons.append(f"音频指纹过近({distances['audio_distance']}<{audio_t})")
    if distances.get("seg_distance", 1.0) < seg_t:
        reasons.append(f"时域序列过近({distances['seg_distance']}<{seg_t})")
    if distances.get("combined_distance", 1.0) < comb_t:
        reasons.append(f"综合指纹过近({distances['combined_distance']}<{comb_t})")
    if reasons:
        return True, ";".join(reasons)
    return False, ""


def compute_full_fingerprint(path: str) -> dict:
    """计算一组完整指纹（视觉 + 音频 + 时域），返回统一结构。"""
    vf = compute_visual_fingerprint(path)
    af = compute_audio_fingerprint(path)
    sf = compute_segment_fingerprint(path)
    return {
        "phash": vf.get("hash_value"),
        "phash_vector": vf.get("vector"),
        "audio_hash": af.get("hash_value"),
        "audio_vector": af.get("vector"),
        "seg_hash": sf.get("hash_value"),
        "seg_vector": sf.get("vector"),
        "duration": vf.get("duration"),
        "resolution": vf.get("resolution"),
    }
