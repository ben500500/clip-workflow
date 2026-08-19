#!/usr/bin/env python3
"""
P0 · env-risk 零成本实测（Mac 侧）

Issue #130「方案 A 落地顺序前置实测」：
在真实 Mac 上启动带 CDP 的**真实 Edge/Chrome**（跑在家庭 IP），**复用现有
`_upload_video` 的 `fc.set_files()` file chooser 路径**（仅把 `cdp_url` 指向本机
真实浏览器），对一个测试文件做一次真实上传，观察微信是否仍返回 `300001` / `env_risk`。

结论分支：
- 若 `status==published` 且 `published_url` 非空（或页面无 `300001`/env_risk 信号）
  →「真实浏览器 + 家庭 IP」已绕过环境级风控，**直接复用 `set_files()` 路径**，
    P1 无需建 OS 对话框（os_dialog）通道。
- 若仍出现 `env_risk`/`300001` → 环境级风控仍触发，P1 需按原设计建 OS 对话框通道。
- 若返回 `need_login` → 账号登录态已过期/未登录，需先用**微信扫码**重新登录再测。

【测试文件来源】
- 任意一段真实 MP4 即可（几十秒即可，建议 >10s，微信发布页对过短视频不友好）。
- 可随手用手机拍/录一段，或从已有成片里挑一个（本脚本只读本地文件，不改任何数据）。
- 脚本只做**一次**真实上传，不会重复发布，安全可逆。

【百花剧社登录态（⚠️ 唯一不可替代的真人动作）】
- 百花剧社账号登录态当前已过期。本脚本开始前，必须先由**号主本人**用手机微信
  （绑定该账号的微信）扫码重新登录：
    1) 在下面第 1 步启动的调试浏览器窗口打开 https://channels.weixin.qq.com ；
    2) 若显示「扫码登录」，用**手机微信**扫二维码 → 手机上点「允许」；
    3) 登录态 cookie 会存进 `--user-data-dir` 指定的 profile，之后每次用同一 profile
       启动即复用，无需重复扫码。
- ⚠️ 不要用其他管理员/运营者的微信扫——登录态会绑错账号。

用法（在真实 Mac 上）：
    1) 用真实 Edge/Chrome 登录视频号创作平台：https://channels.weixin.qq.com
       （百花剧社：用号主微信扫码 + 允许，见上方说明）
    2) 用下列任一方式暴露本机 CDP（二选一，见下面 launch 说明）
    3) 运行：  python3 p0_mac_env_risk_test.py --video <测试视频.mp4> [--cdp <ws|http地址>]
    4) 看输出： PASS / RISK_FAIL / NEED_LOGIN

本脚本直接 import 后端 `VideoChannelPublisher` 并调用其 `_upload_video`，
保证与线上 `_upload_video` 走完全相同的 file-chooser / set_files 逻辑（不复制脆弱的
selector），因此实测结论对线上链路有直接代表性。

⚠️ 非自动化环境限制：本脚本需在真实 Mac + 已登录视频号账号的浏览器上执行，
CI/容器内无法运行（家庭 IP + 真人浏览器指纹正是实测要验证的变量）。
"""

import argparse
import asyncio
import os
import sys

# ---- P0 实测只需 Publisher（不碰 DB/MinIO）。但后端 app.config 的 Settings 在
#      import 时要求 DATABASE_URL / MinIO 密钥等必填，Mac 上未必有 .env。这里在
#      import 前注入占位值，仅用于让 pydantic 校验通过；实测全程不会用到这些连接。
_FAKE_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///p0_dummy.db",
    "MINIO_ACCESS_KEY": "p0-dummy",
    "MINIO_SECRET_KEY": "p0-dummy",
}
for _k, _v in _FAKE_ENV.items():
    os.environ.setdefault(_k, _v)

# ---- 让 import 能找到后端模块 ----
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.join(_THIS_DIR, os.pardir, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.publish_service import (  # noqa: E402
    UploadRiskError,
    UPLOAD_RISK_PROBES,
    VideoChannelPublisher,
)


# 视频号创作平台发布页
CREATOR_URL = "https://channels.weixin.qq.com/platform/post/create"


def build_cdp_url(raw: str) -> str:
    """把用户给的 CDP 地址归一为 Playwright connect_over_cdp 可用的 http/ws URL。

    支持：
      - 纯端口数字（如 9222）→ http://127.0.0.1:9222
      - http(s)://host:port → 原样（connect_over_cdp 接受 http，会自动取 /json/version）
      - ws:// 或完整 devtools ws 地址 → 原样
    """
    if not raw:
        raise SystemExit("--cdp 为空：请传本机真实浏览器的调试端口/地址")
    raw = raw.strip()
    if raw.isdigit():
        return f"http://127.0.0.1:{raw}"
    if raw.startswith(("http://", "https://", "ws://", "wss://")):
        return raw
    raise SystemExit(
        f"无法解析 --cdp 值：{raw}。请传端口号(如 9222)、http 地址或 ws 地址"
    )


async def run_p0(video_path: str, cdp_url: str, timeout_s: int = 600) -> dict:
    """执行 P0 实测：真实浏览器 + set_files 路径上传一个测试视频。

    返回结构化结果，包含上传是否成功、是否命中风控信号、判读结论。
    """
    video_path = os.path.abspath(video_path)
    if not os.path.isfile(video_path):
        raise SystemExit(f"测试视频不存在：{video_path}")

    # 实例化与线上同款的 Publisher，仅把 cdp_url 指向本机真实浏览器。
    # require_manual_confirm=False → 让 _publish_body 走 auto-publish，覆盖 upload→
    # wait→click 全链路，能拿到 published_url 才叫真成功。
    pub = VideoChannelPublisher(
        cdp_url=cdp_url,
        cdp_token=None,        # 本机直连真实浏览器，无 cdp_proxy 鉴权
        require_manual_confirm=False,
    )

    print("=" * 72)
    print("P0 · env-risk 实测启动")
    print(f"  CDP      : {cdp_url}")
    print(f"  视频     : {video_path}")
    print(f"  创作页   : {CREATOR_URL}")
    print("=" * 72)

    # 进入发布流程前先探测登录态（百花剧社登录态已过期，需先扫码）。
    # 命中 need_login/expired 直接返回，避免空跑一次真实发布流程。
    try:
        precheck = await pub.check_login_status()
    except Exception as e:  # CDP 连不上也先提示，不进入发布
        print(f"⚠️ 登录态预检失败（CDP 可能未就绪）：{e}")
        print(mac_launch_hint(cdp_url))
        print("\n结论:")
        print("  [ PRECHECK_FAIL ] 请按上面指引拉起带 CDP 的真实浏览器并登录后再重跑。")
        return {"verdict": {"verdict": "PRECHECK_FAIL", "reason": str(e)}}
    precheck_login = precheck.get("status") in ("expired", "error")
    if precheck_login:
        print(f"\n⚠️ 登录态预检：{precheck.get('status')}（账号未登录/已过期）")
        print(wx_scan_login_hint())
        print("结论:")
        print("  [ NEED_LOGIN ] 请先用号主手机微信扫码（扫 + 允许）重新登录后再重跑。")
        return {"verdict": {"verdict": "NEED_LOGIN", "reason": "precheck login expired"}}
    print(f"✓ 登录态预检通过（{precheck.get('status')}）")

    result = await pub.publish(
        video_path=video_path,
        title="P0-env-risk-test",
        description="环境级风控零成本实测（家庭IP+真实浏览器），可忽略",
        tags=["测试"],
    )

    status = result.get("status")
    published_url = result.get("published_url")
    risk_type = result.get("risk_type")
    error = result.get("error")

    print("-" * 72)
    print(f"  status        : {status}")
    print(f"  published_url : {published_url}")
    print(f"  risk_type     : {risk_type}")
    print(f"  error         : {error}")
    print("-" * 72)

    # 登录态过期/未登录：给出微信扫码指引（预检已拦截多数，此处兜底发布后返回值）
    if status == "need_login":
        verdict = {
            "verdict": "NEED_LOGIN",
            "reason": (
                "登录态过期或未登录（status=need_login）。"
                "这是唯一不可替代的真人动作：请先用号主手机微信扫码（扫 + 允许）"
                "重新登录该视频号账号，再重跑本脚本。"
            ),
            "next": "login-then-retry",
        }
        print("\n" + wx_scan_login_hint())
        print(f"\n结论:\n  [ {verdict['verdict']} ]")
        print(f"  {verdict['reason']}")
        return {**result, "verdict": verdict}

    if status == "published" and published_url:
        verdict = {
            "verdict": "PASS",
            "reason": (
                "真实浏览器(家庭IP) + fc.set_files() 路径上传成功，published_url 非空，"
                "未触发 300001/env_risk。→ 方案A 直接复用 set_files() 路径，"
                "P1 无需建 OS 对话框通道。"
            ),
            "next": "P1",
        }
    elif risk_type in ("env_risk", "upload_limited") or "300001" in str(error):
        verdict = {
            "verdict": "RISK_FAIL",
            "reason": (
                f"仍触发风控（risk_type={risk_type}, error={error}）。"
                "真实浏览器+家庭IP 未能绕过环境级风控。"
                "→ P1 需按原设计建 OS 对话框通道（os_dialog / win_uia）。"
            ),
            "next": "P1-os_dialog",
        }
    else:
        verdict = {
            "verdict": "INCONCLUSIVE",
            "reason": (
                f"未进入 published 也未命中明确风控信号（status={status}, error={error}）。"
                "建议重试一次或改用已登录账号重新运行。"
            ),
            "next": "retry-or-check-login",
        }

    print("\n结论:")
    print(f"  [ {verdict['verdict']} ]")
    print(f"  {verdict['reason']}")
    return {**result, "verdict": verdict}


def wx_scan_login_hint() -> str:
    """百花剧社账号「微信扫码重新登录」专属指引（唯一不可替代的真人动作）。"""
    return """
--------------------------------------------------------------------------------
【百花剧社账号 · 微信扫码重新登录（必须由号主本人操作）】
--------------------------------------------------------------------------------
P0 实测 / 真实发布前，百花剧社登录态已过期，必须先重新登录。步骤如下：

  1) 在当前调试浏览器窗口打开视频号创作平台：
       https://channels.weixin.qq.com
  2) 页面若显示「扫码登录」二维码，用**号主本人手机上的微信**扫码，
     手机上出现「视频号助手」登录确认后，点**允许**；
  3) 登录态 cookie 会写入 --user-data-dir 指定的 profile，之后每次用同一
     profile 启动即复用，无需重复扫码；
  4) 登录后回到发布页，确认右上角头像显示的是「百花剧社」，再重跑本脚本。

⚠️ 自动化替代不了这一步：扫码 + 允许必须由号主真人完成（绑定手机 + 指纹）。
⚠️ 不要用其他管理员/运营者的微信扫——登录态会绑错账号、串号。
--------------------------------------------------------------------------------
"""


def mac_launch_hint(cdp_url: str) -> str:
    """给出在真实 Mac 上如何拉起带 CDP 的 Edge/Chrome 并保持登录态的提示。"""
    port = cdp_url.split(":")[-1].split("/")[0] if ":" in cdp_url else "9222"
    return f"""
--------------------------------------------------------------------------------
【Mac 侧拉起真实浏览器（二选一，任选其一即可）】
--------------------------------------------------------------------------------
方式 A（推荐，沿用已登录的真实 Chrome，不新建窗口）：
  1) 完全退出 Chrome：  ⌘Q
  2) 用真实 Edge 打开视频号并登录：  https://channels.weixin.qq.com
     （或继续用 Chrome，保持登录态）
  3) 用带调试口的命令行重启浏览器（Windows 示例；Mac 用 open 传参类似）：
     # Edge（Mac）：
     "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \\
       --remote-debugging-port={port} --user-data-dir="$HOME/.edge-p0" \\
       https://channels.weixin.qq.com
     # Chrome（Mac）：
     "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
       --remote-debugging-port={port} --user-data-dir="$HOME/.chrome-p0" \\
       https://channels.weixin.qq.com
     # 然后登录该窗口里的视频号账号（一次性）
  4) 验证 CDP 可用： curl http://127.0.0.1:{port}/json/version

方式 B（直接连已开调试口的浏览器）：
  - 若你的 Mac 上已有带 --remote-debugging-port 的浏览器在跑，直接给 --cdp 地址即可。

注意：
  - 视频号账号需在**该调试浏览器窗口**内完成扫码登录（登录态 cookie 存在
    --user-data-dir 指定的 profile 里，跨次启动可复用）。
  - 家庭 IP：本测试请在你的家庭网络下运行（不要在机房/云主机上），这正是
    实测要验证的"真实浏览器+家庭IP"两个变量。
--------------------------------------------------------------------------------
"""


def main():
    ap = argparse.ArgumentParser(description="P0 env-risk 零成本实测（真实 Mac + 真实浏览器）")
    ap.add_argument("--video", required=True, help="要上传的测试视频文件路径（mp4 等）")
    ap.add_argument("--cdp", default=None, help="本机真实浏览器 CDP 地址（端口/http/ws）")
    ap.add_argument("--timeout", type=int, default=600, help="上传/发布超时（秒）")
    args = ap.parse_args()

    cdp_url = args.cdp or input(
        "\n请输入真实浏览器 CDP 地址（端口号如 9222，或 http://127.0.0.1:9222）："
    ).strip()
    cdp_url = build_cdp_url(cdp_url)

    print(mac_launch_hint(cdp_url))
    confirm = input("\n浏览器已登录视频号账号并暴露调试端口了吗？(y/N) ").strip().lower()
    if confirm != "y":
        print("已取消。请先按上面提示拉起带 CDP 的真实浏览器并登录后重试。")
        sys.exit(1)

    result = asyncio.run(run_p0(args.video, cdp_url, args.timeout))
    sys.exit(0 if result.get("verdict", {}).get("verdict") == "PASS" else 1)


if __name__ == "__main__":
    main()
