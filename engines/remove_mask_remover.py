#!/usr/bin/env python3
"""
Remove Mask 去水印引擎 —— 基于 ben500500/remove-mask 的「ROI + cv2.inpaint(TELEA)」方案

原理（沿用 remove-mask 仓库《去水印经验总结》思路）：
1. 不区分“哪些像素是水印”：直接把整个水印 ROI 矩形当掩码
2. cv2.INPAINT_TELEA 快速行进法从 ROI 边界向内插值填充（对文字水印优于 NS）
3. 按视频文件名匹配内置 ROI（基于全视频时序分析 + OCR 确认的水印框 + buffer）
4. 覆盖 TL / BR（Seedance 水印规律固定出现在左上 + 右下角）
5. 参数保真：保留原始分辨率/帧率/编码，音频流复制零损耗

两种去水印模式（--mode 切换，同步 ben500500/remove-mask 上游更新）：
- inpaint（默认）：ROI + cv2.inpaint(TELEA) 插值修复，保留原始构图，水印区域被插值填充
- crop：裁切去水印，把包含水印的上下两条水平带裁掉，保留中间无字区域后等比放大回
  原始分辨率、左右对称居中裁回原始宽度。画面无修复痕迹但构图有裁剪/放大。
  适合画面上下无重要内容、宁可损失一点构图也不愿看到修复痕迹的场景。

CLI:
  python remove_mask_remover.py <输入视频> -o <输出视频> [options]

选项:
  -r, --region  x,y,w,h    手动指定水印区域（覆盖文件名匹配；x=列 y=行 w=宽 h=高）
  --scope      small|large 水印 ROI 范围（默认 small：收紧贴合水印文字；large：整角大框）
  --mode       inpaint|crop 去水印模式（默认 inpaint：ROI+插值修复；crop：裁切去水印）
  --radius      N          修补半径（默认 3，仅 inpaint 模式生效）
  --iterations  N          修补迭代次数（默认 1，仅 inpaint 模式生效）
  --source-name NAME       原始文件名（用于匹配内置 ROI；默认取输入文件 basename）

进度约定：向 stdout 输出 PROGRESS:<pct>（与 clip-workflow watermark_runner 一致）。
"""

import argparse
import os
import subprocess
import sys

import cv2

# remove-mask 经验库（ROI 表）共享模块，与其它引擎共用同一份确认过的水印位置
from remove_mask_rois import build_mask, resolve_rois


def process_crop(video_path, output_path, rois):
    """裁切去水印：裁掉覆盖水印的上下水平带，剩余画面等比放大回原高并居中裁回原宽。

    同步自 ben500500/remove-mask 上游 --mode crop 实现：
      顶部水印(TL)下边缘以上、底部水印(BR)上边缘以下整条水平带裁掉，
      保留中间无字区域，等比放大回原始高度，左右对称居中裁回原始宽度。
    """
    print("水印 ROI:", flush=True)
    for c, roi in rois.items():
        print(f"  {c}: {roi}", flush=True)

    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    print(f"Video: {W}x{H} @ {fps:.3f} fps | {total} frames", flush=True)

    # 由 ROI 计算顶部/底部需要裁掉的行数（左右水印只影响缩放后的横向居中，不影响裁剪行）
    # 顶部水印(TL)的 y1 = 裁掉区域下边缘；底部水印(BR)的 y0 = 保留区下边缘
    top = max(r[1] for r in rois.values() if r[1] <= H // 2)      # 顶部裁到 TL 水印下边缘
    bottom = min(r[0] for r in rois.values() if r[0] >= H // 2)   # 底部从 BR 水印上边缘起裁
    crop_h = bottom - top                     # 保留区高度
    scale = H / crop_h                        # 等比放大系数（裁掉后放大回原高）
    crop_w = int(round(W / scale))            # 等比放大回 W×H 前需要裁出的宽度（原图坐标系）
    x0 = (W - crop_w) // 2                    # 左右居中裁
    print(
        f"裁剪区: 顶 {top} 行 / 底 {H - bottom} 行，保留 {crop_h} 行，等比放大 {scale:.4f}x，横向居中裁 {crop_w}px",
        flush=True,
    )

    tmp_video = output_path + '.tmp.mp4'
    audio_tmp = output_path + '.aac'

    # 提取原音频（流复制，无损）；无音轨时静默降级
    print("PROGRESS:3", flush=True)
    has_audio = False
    try:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', video_path,
            '-vn', '-acodec', 'copy', audio_tmp
        ], check=True)
        if os.path.isfile(audio_tmp) and os.path.getsize(audio_tmp) > 0:
            has_audio = True
    except subprocess.CalledProcessError:
        has_audio = False

    print("PROGRESS:8", flush=True)
    # 视频流：rawvideo → libx264 高质量（帧率保持原 fps）
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f'{W}x{H}', '-r', f'{fps:.6f}'.rstrip('0').rstrip('.'),
        '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        tmp_video
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    idx = 0
    print("逐帧裁切中...", flush=True)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        kept = frame[top:bottom, x0:x0 + crop_w]                                # 裁掉水印区
        result = cv2.resize(kept, (W, H), interpolation=cv2.INTER_LANCZOS4)     # 等比放大回原分辨率
        proc.stdin.write(result.tobytes())
        idx += 1
        if idx % 30 == 0 or idx == total:
            pct = 8 + int(idx / total * 82) if total else 90
            print(f"  处理帧 {idx}/{total}", flush=True)
            print(f"PROGRESS:{min(pct, 90)}", flush=True)
    cap.release()
    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        for p in (tmp_video, audio_tmp):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        raise RuntimeError("ffmpeg 视频编码失败")

    # 合并音频
    print("合并音频...", flush=True)
    print("PROGRESS:95", flush=True)
    if has_audio:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', tmp_video, '-i', audio_tmp,
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'copy',
            '-shortest',
            output_path
        ], check=True)
    else:
        os.replace(tmp_video, output_path)

    for p in (tmp_video, audio_tmp):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

    print(f"完成: {output_path} ({idx} 帧)", flush=True)
    print("PROGRESS:100", flush=True)
    return rois


def process(video_path, output_path, rois, radius=3, iterations=1):
    print("水印 ROI:")
    for c, roi in rois.items():
        print(f"  {c}: {roi}", flush=True)

    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Video: {W}x{H} @ {fps:.3f} fps | {total} frames", flush=True)

    mask = build_mask(rois, H, W)
    print(f"mask 总面积: {int(mask.sum() / 255)} px", flush=True)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    tmp_video = output_path + '.tmp.mp4'
    audio_tmp = output_path + '.aac'

    # 提取原音频（流复制，无损）；无音轨时静默降级
    print("提取原音频...", flush=True)
    print("PROGRESS:3", flush=True)
    has_audio = False
    try:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', video_path,
            '-vn', '-acodec', 'copy', audio_tmp
        ], check=True)
        if os.path.isfile(audio_tmp) and os.path.getsize(audio_tmp) > 0:
            has_audio = True
    except subprocess.CalledProcessError:
        has_audio = False

    print("PROGRESS:8", flush=True)
    # 视频流：rawvideo → libx264 高质量（保留实际帧率）
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f'{W}x{H}', '-r', f'{fps:.3f}',
        '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        tmp_video
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    idx = 0
    print("逐帧修补中...", flush=True)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        result = frame.copy()
        for _ in range(iterations):
            result = cv2.inpaint(result, mask, radius, cv2.INPAINT_TELEA)
        proc.stdin.write(result.tobytes())
        idx += 1
        if idx % 30 == 0 or idx == total:
            pct = 8 + int(idx / total * 82) if total else 90
            print(f"  处理帧 {idx}/{total}", flush=True)
            print(f"PROGRESS:{min(pct, 90)}", flush=True)
    cap.release()
    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        for p in (tmp_video, audio_tmp):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        raise RuntimeError("ffmpeg 视频编码失败")

    # 合并音频
    print("合并音频...", flush=True)
    print("PROGRESS:95", flush=True)
    if has_audio:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', tmp_video, '-i', audio_tmp,
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'copy',
            '-shortest',
            output_path
        ], check=True)
    else:
        os.replace(tmp_video, output_path)

    for p in (tmp_video, audio_tmp):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

    print(f"完成: {output_path} ({idx} 帧)", flush=True)
    print("PROGRESS:100", flush=True)
    return rois


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="remove_mask_remover",
        description="Remove Mask 去水印引擎（ROI + cv2.inpaint TELEA / 裁切）",
    )
    parser.add_argument("input", help="输入视频路径")
    parser.add_argument("-o", "--output", help="输出视频路径")
    parser.add_argument(
        "-r", "--region",
        help="手动水印区域 x,y,w,h（覆盖文件名匹配；x=列 y=行 w=宽 h=高）",
    )
    parser.add_argument("--radius", type=int, default=3, help="修补半径（默认 3，仅 inpaint 模式）")
    parser.add_argument("--iterations", type=int, default=1, help="修补迭代次数（默认 1，仅 inpaint 模式）")
    parser.add_argument(
        "--scope", default="small", choices=["small", "large"],
        help="水印 ROI 范围：small=收紧贴合水印文字（默认），large=整角大框覆盖更彻底",
    )
    parser.add_argument(
        "--mode", default="inpaint", choices=["inpaint", "crop"],
        help="去水印模式：inpaint=ROI+插值修复保留原构图（默认）；crop=裁切去水印（等比缩放切掉水印）",
    )
    parser.add_argument(
        "--source-name", default=None,
        help="原始文件名（用于匹配内置 ROI；默认取输入文件 basename）",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    if not args.output:
        root, ext = os.path.splitext(args.input)
        args.output = f"{root}_clean{ext or '.mp4'}"

    manual_region = None
    if args.region:
        try:
            parts = [int(p.strip()) for p in args.region.split(",")]
            assert len(parts) == 4 and all(v >= 0 for v in parts)
            manual_region = tuple(parts)
        except (ValueError, AssertionError):
            print("Error: --region 格式错误，应为 x,y,w,h（如 10,5,120,60）", file=sys.stderr)
            return 1

    radius = max(1, min(args.radius or 3, 20))
    iterations = max(1, min(args.iterations or 1, 5))

    source_name = args.source_name or args.input
    rois = resolve_rois(source_name, manual_region, scope=args.scope)

    try:
        if args.mode == "crop":
            process_crop(args.input, args.output, rois)
        else:
            process(args.input, args.output, rois, radius=radius, iterations=iterations)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 未捕获异常: {e}", file=sys.stderr)
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
