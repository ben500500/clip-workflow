#!/usr/bin/env python3
"""R7 QR 渲染 Spike：验证 headless Chromium 中微信登录二维码渲染可行性。

背景（方案 v3.1 R7 / 4.1 前置）：headless Chromium 中微信登录二维码的渲染
依赖 canvas / GPU，未经验证。本脚本在部署环境（192.168.1.163 或任意 rpa_worker /
backend 容器内）执行，对指定 profile 的 Chromium 调试口：

1. 通过 CDP 连到该 profile（默认 127.0.0.1:<port>）；
2. 导航到视频号创作中心登录页；
3. 定位登录二维码元素并截图；
4. 判定：
   - 能截到 ≥500 bytes 的二维码 PNG → Spike 通过，可走「CDP 抽 QR → 加密存 MinIO → 自服务扫码」链路；
   - 截不到 / 页面无二维码 / 渲染依赖 GPU 失败 → Spike 失败，退化「本机浏览器扫码 + cookie 注入回传」方案（R7）。

用法：
    python3 scripts/qr_render_spike.py --port 9223
    python3 scripts/qr_render_spike.py --port 9224 --host 127.0.0.1 --timeout 30

退出码：0=Spike 通过；1=Spike 失败；2=参数/环境错误。
"""

import argparse
import asyncio
import sys


async def run_spike(port: int, host: str, timeout: int) -> int:
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        print(f"[qr_spike] ERROR: playwright 未安装，无法执行 Spike：{e}")
        return 2

    # 视频号创作者平台登录页
    CREATOR_LOGIN = "https://channels.weixin.qq.com/"
    # 二维码定位选择器（集中管理，可版本化 R18）
    QR_SELECTORS = [
        "img.qrcode",
        "canvas",
        "[class*='qrcode'] img",
        "[class*='login'] img",
        "[class*='qrcode']",
        "[class*='login-guide']",
    ]

    try:
        async with async_playwright() as p:
            print(f"[qr_spike] 连接 CDP: http://{host}:{port}")
            browser = await p.chromium.connect_over_cdp(f"http://{host}:{port}")
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()

            print(f"[qr_spike] 导航到 {CREATOR_LOGIN}")
            await page.goto(CREATOR_LOGIN, wait_until="domcontentloaded", timeout=timeout * 1000)
            await page.wait_for_timeout(3000)

            # 截图整页作佐证
            full_png = await page.screenshot()
            with open("/tmp/qr_spike_page.png", "wb") as f:
                f.write(full_png)
            print(f"[qr_spike] 已保存整页截图 /tmp/qr_spike_page.png ({len(full_png)} bytes)")

            # 逐个选择器尝试定位二维码
            qr_png = None
            found_sel = None
            for sel in QR_SELECTORS:
                el = await page.query_selector(sel)
                if el:
                    try:
                        shot = await el.screenshot()
                        if shot and len(shot) > 500:
                            qr_png = shot
                            found_sel = sel
                            break
                        print(f"[qr_spike]   selector '{sel}' 命中但截图过小({len(shot) if shot else 0} bytes)，跳过")
                    except Exception as e:
                        print(f"[qr_spike]   selector '{sel}' 截图失败：{e}")
                else:
                    print(f"[qr_spike]   selector '{sel}' 未命中")

            await page.close()

            if qr_png:
                with open("/tmp/qr_spike_qr.png", "wb") as f:
                    f.write(qr_png)
                print(f"[qr_spike] ✅ Spike 通过：命中 selector '{found_sel}'，抽到二维码 {len(qr_png)} bytes，已存 /tmp/qr_spike_qr.png")
                print("[qr_spike]   结论：headless Chromium 可渲染/截取微信登录二维码 → 可走「CDP 抽 QR → 加密存 MinIO → 自服务扫码」链路")
                return 0
            else:
                print("[qr_spike] ❌ Spike 失败：未能从页面定位/截取二维码（可能 canvas/GPU 渲染失败，或页面未呈现登录二维码）")
                print("[qr_spike]   结论：建议退化为「本机浏览器扫码 + cookie 注入回传」方案（R7）")
                return 1
    except Exception as e:
        print(f"[qr_spike] ❌ Spike 异常：{e}")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="R7 QR 渲染 Spike")
    ap.add_argument("--port", type=int, default=9223, help="Chromium 调试端口（默认 9223）")
    ap.add_argument("--host", default="127.0.0.1", help="Chromium 调试 host（默认 127.0.0.1）")
    ap.add_argument("--timeout", type=int, default=30, help="页面加载超时秒数（默认 30）")
    args = ap.parse_args()

    try:
        code = asyncio.run(run_spike(args.port, args.host, args.timeout))
    except KeyboardInterrupt:
        print("\n[qr_spike] 被中断")
        return 130
    return code


if __name__ == "__main__":
    sys.exit(main())
