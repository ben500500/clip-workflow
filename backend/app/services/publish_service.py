"""
Publish service - RPA-based video publishing to short video platforms.

Uses Playwright to automate video uploads to platforms like WeChat Video Channel,
Douyin, and Kuaishou. Supports screenshot-based manual confirmation workflow.

设计说明（一键发布收敛）：
- 唯一的 Publisher 实现收敛到本模块，由 backend Celery worker 通过 CDP 连接
  rpa_worker 容器内常驻的 Chromium 执行（CHROME_DEBUG_HOST:CHROME_DEBUG_PORT）。
- 人工确认流程：publish() 填写表单后返回 pending_confirm，并把已填好表单的
  Playwright page 缓存到进程内 _PENDING_TABS；confirm_publish() 复用同一 tab
  点击「发布」，避免重新打开页面导致表单丢失。
- 若确认时缓存失效（worker 重启/超时），退化为重新打开创作中心并尽力点击发布。
"""

import asyncio
import logging
import os
import tempfile
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class PublishTimeoutError(Exception):
    """发布结果确认超时。

    与 P0-1 假成功根因对应：`_wait_for_publish` 不应在超时后以 `except` 兜底
    静默返回 (url, None) 当作已发布，而应显式抛出本异常，让调用方（publish /
    confirm_publish）走 `failed`/`error` 分支，避免把"没发出去"误判为"发布成功"。
    """


class UploadRiskError(Exception):
    """上传被平台风控/环境级拒绝（区别于普通超时/网络失败）。

    视频号等平台在上传阶段可能返回 `300001`/`upload_params` 等环境级风控信号，
    表现为"上传无进展或直接被拒"。这类失败不应与普通超时混为一谈：
    - 语义上它是账号/环境受限（风控），而非瞬时故障；
    - 处置上不应自动重试（重试只会重复消耗账号安全额度），应走 `upload_limited` /
      `env_risk` 分级并进死信队列人工/定时重放。

    `risk_code` 承载探测到的风控码/文案分类，供上层落 `risk_type`。
    """

    def __init__(self, risk_code: str = "upload_limited", detail: str = ""):
        super().__init__(detail or risk_code)
        self.risk_code = risk_code
        self.detail = detail


# 上传/环境级风控信号的 DOM/文案探测规则（集中管理，微信改版时可热修）
# key=探测出的分类，value=命中关键词（页面文本/URL/类名，大小写不敏感）
UPLOAD_RISK_PROBES: dict = {
    "env_risk": [   # 环境级风控（300001 / upload_params / 设备环境异常）
        "300001", "upload_params", "环境异常", "设备异常", "存在风险",
        "当前环境", "操作频繁", "请稍后再试", "验证", "安全校验",
    ],
    "upload_limited": [   # 账号级上传受限（发布额度/功能限制）
        "上传失败", "上传受限", "发布受限", "功能受限", "无法上传",
        "次数已达上限", "今日已用完", "被限制", "无法发布",
    ],
    "need_login": [   # 登录态被踢/失效
        "登录已失效", "请先登录", "重新登录", "登录过期", "扫码登录",
    ],
}


# 进程内待确认发布 tab 缓存：publish_task_id -> {"browser": Browser, "page": Page}
# backend worker 采用 --concurrency=1 串行处理 publish 队列任务，publish 与后续
# confirm 在同一 worker 进程内执行，模块级缓存跨任务存活可用。
_PENDING_TABS: dict = {}
_PENDING_TABS_LOCK = threading.Lock()

# 进程级共享 Playwright 实例：backend worker 常驻，所有 CDP 连接复用同一个
# driver，避免缓存 tab 的 browser 代理因 driver 被 GC 而失效。
# C3：收敛到 playwright_manager 进程级单例（引用计数 + 空闲回收），此处以
# get_shared() 永久 pin 方式持有，保证跨任务复用待确认 tab 的 browser 代理安全。
_shared_pw = None
_shared_pw_lock = threading.Lock()


async def _get_playwright():
    """获取进程级共享 Playwright 实例（懒启动，worker 进程内常驻）。"""
    global _shared_pw
    if _shared_pw is None:
        # Celery worker 默认单进程；用锁保证多线程/多 worker 场景下只初始化一次
        with _shared_pw_lock:
            if _shared_pw is None:
                from app.services.playwright_manager import get_playwright_manager
                _shared_pw = await get_playwright_manager().get_shared()
    return _shared_pw


def _cache_pending_tab(task_id: str, browser, page) -> None:
    """缓存已填好表单的待确认页面。"""
    with _PENDING_TABS_LOCK:
        # 同任务重复发布时先释放旧 tab
        old = _PENDING_TABS.pop(task_id, None)
        if old:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(old["browser"].close())
                else:
                    loop.run_until_complete(old["browser"].close())
            except Exception:
                pass
        _PENDING_TABS[task_id] = {"browser": browser, "page": page}


def _pop_pending_tab(task_id: str):
    """取出并移除待确认页面缓存。"""
    with _PENDING_TABS_LOCK:
        return _PENDING_TABS.pop(task_id, None)


def release_pending_tab(task_id: str) -> None:
    """释放待确认 tab（取消/失败时调用）。"""
    entry = _pop_pending_tab(task_id)
    if entry:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(entry["browser"].close())
            else:
                loop.run_until_complete(entry["browser"].close())
        except Exception:
            pass


class VideoChannelPublisher:
    """
    Playwright-based publisher for WeChat Video Channel (微信视频号).

    Workflow:
    1. Connect to Chrome via debug port or launch new browser
    2. Navigate to the Video Channel creator page
    3. Upload video file
    4. Set title, description, tags, cover image
    5. Optionally attach mini program link
    6. Take screenshot for manual confirmation
    7. Wait for user confirmation or auto-publish
    """

    PLATFORM = "wechat_channel"
    CREATOR_URL = "https://channels.weixin.qq.com/platform/post/create"
    # 视频号没有独立的话题输入框：话题以 `#话题#` 形式嵌在视频描述里。
    # 该开关为 True 时，publish/confirm 会把 tags 拼进描述末尾、不再调用 `_set_tags`
    # （避免误找无关输入框导致标签静默丢失）。抖音/快手有独立话题框，覆盖为 False。
    EMBED_TAGS_IN_DESC = True

    def __init__(
        self,
        chrome_debug_port: int = 9222,
        cookie_file: Optional[str] = None,
        require_manual_confirm: bool = True,
        cdp_url: Optional[str] = None,
        cdp_token: Optional[str] = None,
    ):
        self.chrome_debug_port = chrome_debug_port
        self.cookie_file = cookie_file
        self.require_manual_confirm = require_manual_confirm
        # 多运营者（R19）：显式 CDP 目标地址 + 短期访问 token（经 cdp_proxy 鉴权转发）
        self.cdp_url = cdp_url
        self.cdp_token = cdp_token
        self.browser = None
        self.page = None
        self._playwright = None

    async def _connect(self) -> None:
        """连接常驻 Chromium（CDP）或启动独立浏览器。

        多运营者（flag=true）时使用 cdp_url + cdp_token（注入 Authorization 头，R19）；
        否则按 chrome_debug_port 连 rpa_worker（一期旧链路，零侵入）。
        """
        self._playwright = await _get_playwright()
        if self.cdp_url:
            # R19：握手前注入 Authorization: Bearer <token>，由 cdp_proxy 校验后转发
            headers = {}
            if self.cdp_token:
                headers["Authorization"] = f"Bearer {self.cdp_token}"
            self.browser = await self._playwright.chromium.connect_over_cdp(
                self.cdp_url, headers=headers
            )
        elif self.chrome_debug_port:
            from app.config import settings as s
            self.browser = await self._playwright.chromium.connect_over_cdp(
                f"http://{s.CHROME_DEBUG_HOST}:{self.chrome_debug_port}"
            )
            context = (
                self.browser.contexts[0]
                if self.browser.contexts
                else await self.browser.new_context()
            )
        else:
            self.browser = await self._playwright.chromium.launch(headless=True)
            context = await self.browser.new_context()
        self.page = await context.new_page()

    async def publish(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list] = None,
        cover_file_key: Optional[str] = None,
        mini_program_link: Optional[str] = None,
        publish_jump: Optional[list] = None,
        task_id: Optional[str] = None,
        publish_comments: Optional[list] = None,
        location: Optional[str] = None,
    ) -> dict:
        """发布整体超时护栏：整个发布流程（上传/填表/跳转/提交）最长 900s，
        超时强制 failed 并释放连接，避免任一环节卡死占住 publish worker
        （concurrency=1，卡死会阻塞所有后续发布）。"""
        try:
            return await asyncio.wait_for(
                self._publish_body(
                    video_path, title, description, tags, cover_file_key,
                    mini_program_link, publish_jump, task_id, publish_comments,
                    location,
                ),
                timeout=900,
            )
        except asyncio.TimeoutError:
            logger.error("Publish timed out after 900s (overall guard), failing")
            await self._close_connection()
            return {
                "success": False,
                "status": "timeout",
                "error": "Publish timed out after 900s (overall guard)",
                "screenshot_path": None,
                "published_url": None,
                "published_id": None,
            }
        except Exception as e:
            logger.error(f"Publishing failed: {e}", exc_info=True)
            await self._close_connection()
            return {
                "success": False,
                "status": "error",
                "error": str(e),
                # PR①：风控拒发时透出 risk_type，供 worker 落 upload_limited/env_risk
                "risk_type": getattr(e, "risk_code", None),
                "screenshot_path": None,
                "published_url": None,
                "published_id": None,
            }

    async def _publish_body(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list] = None,
        cover_file_key: Optional[str] = None,
        mini_program_link: Optional[str] = None,
        publish_jump: Optional[list] = None,
        task_id: Optional[str] = None,
        publish_comments: Optional[list] = None,
        location: Optional[str] = None,
    ) -> dict:
        """
        Execute the full publishing workflow (body, wrapped by publish() timeout guard).
        """
        try:
            await self._connect()

            # Check login state
            if await self._need_login():
                await self._close_connection()
                return {
                    "success": False,
                    "status": "need_login",
                    "error": "Not logged in. Please login first via Chrome debug port.",
                    "screenshot_path": None,
                }

            # Navigate to creator page
            await self.page.goto(self.CREATOR_URL, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # 上传前预检（PR①）：轻量探测页面上是否已出现账号级风控/登录失效信号，
            # 命中则提前返回，避免白白消耗 worker 与账号安全额度进入上传。
            pre_risk = await self._probe_upload_risk_signal()
            if pre_risk == "need_login":
                await self._close_connection()
                return {
                    "success": False,
                    "status": "need_login",
                    "error": "Login session expired before upload.",
                    "screenshot_path": None,
                }
            if pre_risk in ("env_risk", "upload_limited"):
                await self._close_connection()
                return {
                    "success": False,
                    "status": "error",
                    "error": f"pre-upload risk signal: {pre_risk}",
                    "risk_type": pre_risk,
                    "screenshot_path": None,
                }

            # Upload video
            await self._upload_video(video_path)

            # Set title and description
            await self._set_title(title)
            if self.EMBED_TAGS_IN_DESC and tags:
                # 视频号：话题嵌进描述（`#话题#` 形式），没有独立话题框
                description = self._merge_tags_into_description(description, tags)
            if description:
                await self._set_description(description)

            # 发布页「位置」配置（按账号注入，P2）：有值才定位，避免干扰默认行为
            if location:
                await self._set_location(location)

            # Set tags（仅抖音/快手等有独立话题框的平台走独立 `_set_tags`）
            if tags and not self.EMBED_TAGS_IN_DESC:
                await self._set_tags(tags)

            # Set cover image if provided
            if cover_file_key:
                await self._set_cover(cover_file_key)

            # 发布跳转配置（端原生/小程序）→ 在视频号发布页选择对应跳转类型
            if publish_jump:
                await self._select_jump_type(publish_jump)

            # Attach mini program link if provided
            if mini_program_link:
                await self._attach_mini_program(mini_program_link)

            # Take screenshot for review
            screenshot_path = await self._take_screenshot()

            if self.require_manual_confirm:
                # 保留已填好表单的 tab，供 confirm 复用点击发布（进程内缓存）
                if task_id:
                    _cache_pending_tab(task_id, self.browser, self.page)
                    # 多运营者（R13/R18）：同时把结构化 payload 外移到 Redis，
                    # 供 worker 重启/多副本时 confirm 幂等重填（含 selector 版本校验）
                    await self._save_pending_payload(
                        task_id, title, description, tags, cover_file_key, mini_program_link, publish_jump, publish_comments, location
                    )
                    # 连接对象交由缓存管理，不在此关闭
                    self.browser = None
                    self.page = None
                else:
                    await self._close_connection()
                return {
                    "success": True,
                    "status": "pending_confirm",
                    "screenshot_path": screenshot_path,
                    "published_url": None,
                    "published_id": None,
                    "error": None,
                }
            else:
                # Auto-publish
                await self._click_publish()
                published_url, published_id = await self._wait_for_publish()
                # 发布后置顶神评（可选，探活式；失败不阻断发布成功）
                if published_url and publish_comments:
                    await self._post_publish_comments(published_url, publish_comments)
                await self._close_connection()
                return {
                    "success": True,
                    "status": "published",
                    "screenshot_path": screenshot_path,
                    "published_url": published_url,
                    "published_id": published_id,
                    "error": None,
                }

        except Exception as e:
            logger.error(f"Publishing failed: {e}", exc_info=True)
            await self._close_connection()
            return {
                "success": False,
                "status": "error",
                "error": str(e),
                # PR①：风控拒发时透出 risk_type，供 worker 落 upload_limited/env_risk
                "risk_type": getattr(e, "risk_code", None),
                "screenshot_path": None,
                "published_url": None,
                "published_id": None,
            }

    async def _post_publish_comments_from_payload(self, task_id, published_url):
        """从 Redis 待确认 payload 中取神评并在发布后触发置顶评论（探活式，失败不阻断）。"""
        if not task_id or not published_url:
            return
        try:
            from app.services import multi_operator
            pending = await multi_operator.get_pending(task_id)
            comments = (pending or {}).get("publish_comments") or []
            if comments:
                await self._post_publish_comments(published_url, comments)
        except Exception as e:
            logger.warning(
                "post-publish comments from payload failed (non-blocking): %s", e
            )

    async def _post_publish_comments(self, published_url: str, comments: list):
        """发布后置顶神评（视频号，探活式保守实现，失败不阻断发布）。

        短片制作产线会产出三条互动神评（`PublishMaterial.comments`），本方法在视频
        发布成功后尝试前往成品详情页，在评论区发表神评并置顶，拉高互动率。

        ⚠️ 视频号评论区 DOM 随版本变化较大，这里采用**探活式**策略：
          - 定位评论区输入框失败 → 记录日志后跳过，绝不抛异常阻断发布成功；
          - 置顶按钮探不到 → 仅发表不置顶，避免误操作；
        
        为避免误把神评发到无关视频/触发风控，只有显式传入 `publish_comments`
        （来自所选发布素材的神评）时才会执行本动作。
        """
        if not published_url or not comments:
            return
        try:
            await self.page.goto(published_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            comment_input = await self.page.query_selector(
                "textarea[placeholder*='评论'], [class*='comment'] textarea, "
                "[class*='comment'] input, [placeholder*='说点什么']"
            )
            if not comment_input:
                logger.info(
                    "post-publish comment input not found on %s, skip comments (non-blocking)",
                    published_url,
                )
                return
            for idx, comment in enumerate(comments):
                content = (
                    comment.get("content")
                    if isinstance(comment, dict)
                    else str(comment)
                )
                if not content:
                    continue
                await comment_input.fill(content)
                await asyncio.sleep(1)
                send_btn = await self.page.query_selector(
                    "[class*='comment'] button, button:has-text('发表'), button:has-text('发送')"
                )
                if send_btn:
                    await send_btn.click()
                    await asyncio.sleep(1.5)
                # 尝试置顶第一条神评（可选，探不到即跳过）
                if idx == 0:
                    pin_btn = await self.page.query_selector(
                        "[class*='pin'] button, [class*='top'] button, "
                        "button:has-text('置顶')"
                    )
                    if pin_btn:
                        try:
                            await pin_btn.click()
                            await asyncio.sleep(1)
                        except Exception:
                            pass
            logger.info("post-publish comments sent for %s", published_url)
        except Exception as e:
            logger.warning(
                "post-publish comments failed (non-blocking): %s", e, exc_info=True
            )

    async def _close_connection(self) -> None:
        """关闭当前 publisher 持有的连接（pending tab 由缓存管理，不在此关闭）。

        共享 Playwright 实例不在此 stop（进程级常驻），只关闭浏览器连接。
        """
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
        self._playwright = None
        self.page = None

    async def _need_login(self) -> bool:
        """Check if the current session requires login."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            # Check for login indicators (e.g., QR code or login button)
            login_selector = await self.page.query_selector(
                ".login-guide, .qrcode-login, [class*='login']"
            )
            return login_selector is not None
        except Exception:
            return True

    async def _probe_upload_risk_signal(self) -> Optional[str]:
        """轻量探测页面上是否存在风控/登录失效信号，命中返回分类，否则 None。

        从 URL、可见文本、常见弹层文案中匹配 `UPLOAD_RISK_PROBES` 的关键词，
        用于：
        - `_wait_for_upload` 超时/不可播放时区分"普通超时"与"风控拒发"；
        - `_publish_body` 上传前预检，避免白白消耗 worker 与账号安全额度。

        探测本身是只读的，不产生副作用；命中则返回分类（env_risk / upload_limited /
        need_login），供上层抛 `UploadRiskError(risk_code=分类)` 或提前返回。
        """
        try:
            url = await self.page.url()
            text = await self.page.evaluate("""() => {
                // 取 body 可见文本 + 常见弹层/提示文本，控制长度避免过重
                const parts = [document.title || ''];
                const body = document.body ? document.body.innerText : '';
                parts.push(body ? body.slice(0, 3000) : '');
                // 弹层/提示区域
                for (const sel of ['.weui-mask, .wx-msg, [class*=toast], [class*=popup], '
                                    '[class*=dialog], [class*=modal], [class*=notice]']) {
                    try {
                        const el = document.querySelector(sel);
                        if (el && el.innerText) parts.push(el.innerText.slice(0, 800));
                    } catch (e) {}
                }
                return parts.join('\n').toLowerCase();
            }""")
            haystack = f"{url.lower()} {text}"
            for category, keywords in UPLOAD_RISK_PROBES.items():
                for kw in keywords:
                    if kw.lower() in haystack:
                        logger.warning("upload risk signal hit: %s (kw=%s)", category, kw)
                        return category
        except Exception as e:
            logger.warning("risk probe failed (non-fatal): %s", e)
        return None

    async def _upload_video(self, video_path: str):
        """Upload the video file through the file input element."""
        await self.page.wait_for_timeout(8000)
        # 优先：点击上传区触发 file chooser 并对其 set_files——保证命中真正绑定
        # 上传逻辑的 input。实测发布页存在 114 个隐藏 file input，直接 set_input_files
        # 可能命中无效占位 input，导致"set 成功但页面无任何上传"（空表单静默通过）。
        uploaded = False
        try:
            # 注意：text= 引擎语法不能与 CSS 选择器混用，这里用纯 CSS
            zone = self.page.locator(
                "[class*='upload'], [class*='upload-area'], [class*='upload-box']"
            ).first
            async with self.page.expect_file_chooser(timeout=15000) as fc_info:
                await zone.click(timeout=10000)
            fc = await fc_info.value
            await fc.set_files(video_path)
            uploaded = True
        except Exception as e:
            logger.warning("file chooser upload failed, fallback to input set: %s", e)
        if not uploaded:
            try:
                # 兜底：对带视频 accept 的 input 直接 set（旧路径）
                await self.page.locator(
                    "input[type='file'][accept*='video']"
                ).first.set_input_files(video_path, timeout=60000)
            except Exception:
                raise RuntimeError("Cannot find video upload input element")
        # Wait for upload to complete
        await self._wait_for_upload()

    async def _wait_for_upload(self, timeout: int = 600):
        """Wait for the video upload to complete (up to timeout seconds).

        P1-3 修复：不再以泛化的 `upload-success/preview` 类名选择器作为成功判据
        （实测视频上传区为空时这些选择器可能被无关元素命中而误报成功），改为等待
        页面上**真实出现带 src 的 <video> 预览元素**，确认视频确实已渲染成功。
        找不到则抛 RuntimeError，让上游走失败分支，避免"上传未完成就点发表"。
        """
        try:
            await self.page.wait_for_selector(
                "video[src], video source[src], [class*='preview'] video",
                timeout=timeout * 1000,
            )
            await asyncio.sleep(3)  # Extra wait for processing
            # 二次确认（严格判据）：video 元素 readyState>=2 且有真实时长 duration>0
            # 才算上传成功。页面可能存在"空 video 元素 + 残留 blob src"的假阳性
            # （set 到无效 input 时也会出现），src 非空不代表真上传。短轮询最长 60s。
            uploaded = False
            for _ in range(30):
                state = await self.page.evaluate("""() => {
                    const v = document.querySelector('video');
                    return v ? {
                        rs: v.readyState || 0,
                        dur: v.duration || 0,
                        src: v.getAttribute('src') || v.currentSrc || '',
                    } : { rs: 0, dur: 0, src: '' };
                }""")
                if (state.get("rs") or 0) >= 2 and (state.get("dur") or 0) > 0:
                    uploaded = True
                    break
                await asyncio.sleep(2)
            if not uploaded:
                risk = await self._probe_upload_risk_signal()
                if risk:
                    raise UploadRiskError(
                        risk_code=risk,
                        detail=f"upload rejected by platform risk control ({risk})",
                    )
                raise RuntimeError("video not actually playable (readyState/duration)")
        except UploadRiskError:
            raise
        except Exception:
            logger.warning("Upload wait timed out or video not ready, failing (P1-3)")
            risk = await self._probe_upload_risk_signal()
            if risk:
                raise UploadRiskError(
                    risk_code=risk,
                    detail=f"upload wait failed, risk signal detected ({risk})",
                )
            raise RuntimeError("video upload did not complete in time (no playable <video>)")

    async def _set_title(self, title: str):
        """Set the video title.

        P1-4 修复：视频号短标题上限 16 字，超限会触发页面红字限制且"发表"按钮
        可能置灰，是 P0-1 假成功的诱因之一。这里在填充前统一截断到 16 字。
        """
        if title and len(title) > 16:
            logger.warning(
                "title truncated to 16 chars for video channel (P1-4): %s -> %s",
                title, title[:16],
            )
            title = title[:16]
        # 视频号服务端处理视频期间标题输入框可能 disabled / 尚未渲染，
        # 静默跳过会以空标题继续发布（平台拒发且流程卡死）。这里轮询等待
        # 输入框出现并可编辑（最长约 60s），仍不可编辑则明确失败。
        title_input = None
        for _ in range(12):
            title_input = await self.page.query_selector(
                "[class*='title'] textarea, [class*='title'] input, [placeholder*='标题']"
            )
            if title_input:
                try:
                    if await title_input.is_editable():
                        break
                except Exception:
                    pass
            await asyncio.sleep(5)
        if title_input:
            try:
                if not await title_input.is_editable():
                    # 已出现但不可编辑：再等最后一轮
                    for _ in range(6):
                        await asyncio.sleep(5)
                        if await title_input.is_editable():
                            break
                    if not await title_input.is_editable():
                        raise RuntimeError("title input not editable in time")
                await title_input.fill("")
                await title_input.fill(title)
                return
            except RuntimeError:
                raise
            except Exception:
                pass
        logger.warning("title input not editable/found in time, failing (empty title would be rejected)")
        raise RuntimeError("title input not editable/found in time")

    async def _set_description(self, description: str):
        """Set the video description."""
        desc_input = await self.page.query_selector(
            "[class*='desc'] textarea, [class*='description'] textarea, [placeholder*='描述']"
        )
        if desc_input:
            await desc_input.fill("")
            await desc_input.fill(description)

    async def _set_location(self, location: str):
        """Set the publish-page「位置」控件（P2，按账号注入）。

        位置输入在视频号发布页通常是一个搜索/选择框（输入城市后从下拉选中）。
        这里先尝试输入位置文本并回车选中候选；若页面无对应控件（不同版本/改版）
        则记录日志跳过，不阻断发布（位置属选填，宁可留空也不误操作）。
        """
        try:
            loc_input = await self.page.query_selector(
                "[placeholder*='位置'], [class*='location'] input, [class*='locate'] input, [class*='region'] input"
            )
            if not loc_input:
                logger.info(
                    "location control not found on publish page, skip (optional): %s",
                    location,
                )
                return
            await loc_input.click()
            await asyncio.sleep(0.5)
            await loc_input.fill(location)
            # 触发下拉候选并选中第一项（按回车/点击候选项）
            await loc_input.press("Enter")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("set location failed (optional, skip): %s", e)

    def _merge_tags_into_description(self, description: str, tags: list) -> str:
        """把话题标签拼进视频描述末尾（视频号话题是嵌在描述里的 `#话题#`，无独立框）。

        已有 `#话题#` 时不重复追加，避免描述里话题重复。
        """
        cleaned = [t for t in (tags or []) if t]
        if not cleaned:
            return description
        # 拼接 `#话题#` 形式（去掉 tag 本身可能带的多余 #）
        topic_str = "".join(f"#{str(t).strip().lstrip('#')}#" for t in cleaned)
        if not topic_str:
            return description
        if description:
            return f"{description}\n{topic_str}"
        return topic_str

    async def _set_tags(self, tags: list):
        """Set video tags.

        视频号没有独立的话题输入框（话题嵌在描述里），此方法为占位空实现；
        真实话题由 `_merge_tags_into_description` 拼进描述。仅在继承类
        （抖音/快手等有独立话题框的平台）覆盖实现时才会实际写入。
        """
        logger.info(
            "%s has no standalone tag input (tags embedded in description), skip _set_tags",
            self.PLATFORM,
        )

    async def _set_cover(self, cover_file_key: str):
        """Set the video cover image."""
        # Cover key is a MinIO object key; download it locally first.
        local_cover = cover_file_key
        if cover_file_key and not os.path.isfile(cover_file_key):
            from app.services.minio_service import download_to_file

            local_cover = os.path.join(
                tempfile.gettempdir(),
                f"cover_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg",
            )
            ok = await download_to_file("raw-footage", cover_file_key, local_cover)
            if not ok:
                logger.warning("Failed to download cover image from MinIO: %s", cover_file_key)
                return

        cover_btn = await self.page.query_selector(
            "[class*='cover'] [class*='upload'], [class*='cover'] button"
        )
        if cover_btn:
            async with self.page.expect_file_chooser() as fc_info:
                await cover_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(local_cover)
            await asyncio.sleep(2)

    async def _select_jump_type(self, publish_jump: list):
        """在视频号发布页选择「跳转类型」：端原生=视频号剧集，小程序=小程序短剧。

        账号的发布跳转配置（端原生/小程序，可单选或两者都选）驱动此处选择：
        两者都选时优先选择「小程序短剧」（带渠道归因，收益链路更完整）；
        仅选端原生时选择「视频号剧集」；均未配置则跳过（不干扰默认行为）。
        找不到对应控件时静默跳过，避免阻断整条发布链路。
        """
        try:
            has_native = "native" in (publish_jump or [])
            has_mini = "mini_program" in (publish_jump or [])
            if not has_native and not has_mini:
                return
            # 目标文案：优先「小程序短剧」（更完整归因），否则「视频号剧集」
            target = "小程序短剧" if has_mini else "视频号剧集"
            option = await self.page.query_selector(
                f"text={target}"
            )
            if not option:
                logger.info("jump-type option '%s' not found, skip", target)
                return
            await option.click()
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning("select jump type failed (non-blocking): %s", e)

    async def _attach_mini_program(self, link: str):
        """Attach a mini program link to the video."""
        link_btn = await self.page.query_selector(
            "[class*='mini-program'], [class*='miniprogram'], [class*='link-btn']"
        )
        if link_btn:
            await link_btn.click()
            await asyncio.sleep(1)
            link_input = await self.page.query_selector(
                "input[placeholder*='链接'], input[placeholder*='link']"
            )
            if link_input:
                await link_input.fill(link)
                await asyncio.sleep(1)
                confirm_btn = await self.page.query_selector(
                    "button:has-text('确定'), button:has-text('确认')"
                )
                if confirm_btn:
                    await confirm_btn.click()

    async def _take_screenshot(self) -> str:
        """Take a screenshot of the current page for review."""
        screenshot_path = os.path.join(
            tempfile.gettempdir(),
            f"publish_screenshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png",
        )
        await self.page.screenshot(path=screenshot_path, full_page=True)
        return screenshot_path

    async def _click_publish(self):
        """Click the publish/submit button."""
        # 视频号发布页实际按钮文案为「发表」；先精确匹配，再回退旧选择器
        try:
            btn = self.page.get_by_role("button", name="发表", exact=True).first
            await btn.click(timeout=15000)
            return
        except Exception:
            pass
        try:
            publish_btn = await self.page.query_selector(
                "button:has-text('发布'), button:has-text('发表'), "
                "button:has-text('Publish'), [class*='publish-btn']"
            )
            if publish_btn:
                await publish_btn.click()
                return
        except Exception:
            pass
        raise RuntimeError("Cannot find publish button")

    async def _wait_for_publish(self, timeout: int = 60) -> tuple:
        """Wait for the publish action to complete and return (url, id).

        P0-1 修复：
        - **以 success 页 URL 为主判据**：等待地址跳转到发布成功页，URL 命中才算成功；
        - published_id 仅作辅助（`[data-id]` 选择器太宽泛，可能命中无关元素，不再作为
          成功判据）；
        - 超时不再以 `except` 兜底静默返回 (url, None)，而是显式抛 `PublishTimeoutError`，
          让调用方走 failed/error 分支，杜绝"假成功"。
        """
        try:
            # 主判据：URL 跳到成功页。视频号成功页含 /success 或 published 结果页特征。
            await self.page.wait_for_url(
                "**/success**",
                timeout=timeout * 1000,
            )
            await asyncio.sleep(2)
            current_url = self.page.url
            # 辅助提取 published_id（仅尽力而为，不因取不到而判失败）
            published_id = None
            try:
                id_el = await self.page.query_selector("[class*='post-id']")
                if id_el:
                    published_id = await id_el.get_attribute("data-id")
            except Exception:
                published_id = None
            return current_url, published_id
        except Exception:
            # P0-1：超时即失败，交由调用方判定 failed，而非当成功返回
            raise PublishTimeoutError(
                "publish result not confirmed: page did not reach success URL within "
                f"{timeout}s (url={self.page.url})"
            )

    async def _save_pending_payload(
        self,
        task_id: str,
        title: str,
        description: str,
        tags: Optional[list],
        cover_file_key: Optional[str],
        mini_program_link: Optional[str],
        publish_jump: Optional[list] = None,
        publish_comments: Optional[list] = None,
        location: Optional[str] = None,
    ) -> None:
        """把待确认发布的结构化 payload 外移到 Redis（R13/R18）。

        不缓存 page 对象；存标题/描述/标签/封面key/小程序链接 + selector 版本号，
        confirm 时据此全量幂等重填（绝不半填）。TTL 30min。
        """
        try:
            from app.services import multi_operator
            payload = {
                "account_id": None,  # 由 celery 层回填 account_id
                "profile_id": None,
                "cdp_url": self.cdp_url or (
                    f"http://{self.chrome_debug_port}" if self.chrome_debug_port else None
                ),
                "title": title,
                "description": description,
                "tags": tags or [],
                "cover_key": cover_file_key,
                "mini_program_link": mini_program_link,
                "publish_jump": publish_jump or [],
                # 发布页「位置」配置（按账号注入，P2），confirm 重填时恢复
                "location": location,
                # 发布后置顶神评（可选，来自发布素材 comments；探活式，失败不阻断）
                "publish_comments": publish_comments or [],
                # 选择器集中管理并带版本号（R18）：confirm 前校验页面结构匹配
                "selector_version": "v1",
            }
            await multi_operator.save_pending(task_id, payload)
        except Exception as e:
            logger.warning(f"save pending payload to Redis failed: {e}")

    async def _refill_pending_form(self, payload: dict, task_id: Optional[str] = None) -> bool:
        """按 Redis payload 全量幂等重填表单（R13/R18）。

        重填前先校验 selector_version 与当前页面结构是否匹配；不匹配即冻结（置
        selector_mismatch）并触发人工介入，绝不静默乱填/半填。返回 False 表示失败。
        """
        try:
            # R18：前置 selector 校验 —— 以关键表单控件哨兵存在性为判据
            if not await self._selector_ok():
                logger.error("selector version mismatch, freeze pending for manual intervention")
                try:
                    from app.services import multi_operator
                    if task_id:
                        await multi_operator.freeze_pending(task_id)
                except Exception:
                    pass
                return False
            # 清空再填（全量幂等），避免半填
            if payload.get("title"):
                await self._set_title(payload["title"])
            # 视频号：话题嵌进描述，confirm 幂等重填时同样把 tags 拼进描述，避免话题丢失
            description = payload.get("description") or ""
            tags = payload.get("tags") or []
            if self.EMBED_TAGS_IN_DESC and tags:
                description = self._merge_tags_into_description(description, tags)
            if description:
                await self._set_description(description)
            if tags and not self.EMBED_TAGS_IN_DESC:
                await self._set_tags(tags)
            if payload.get("cover_key"):
                await self._set_cover(payload["cover_key"])
            if payload.get("publish_jump"):
                await self._select_jump_type(payload["publish_jump"])
            if payload.get("mini_program_link"):
                await self._attach_mini_program(payload["mini_program_link"])
            # 发布页「位置」配置：confirm 幂等重填时同样恢复
            if payload.get("location"):
                await self._set_location(payload["location"])
            return True
        except Exception as e:
            logger.error(f"refill pending form failed: {e}", exc_info=True)
            return False

    async def _selector_ok(self) -> bool:
        """前置校验当前页面结构是否匹配已知 selector 版本（R18）。

        以标题输入框 + 发布按钮等关键控件哨兵存在性为判据；微信改版/页面异常时返回 False。
        """
        try:
            title = await self.page.query_selector("input[placeholder*='标题'], [class*='title'] input")
            publish = await self.page.query_selector(
                "[class*='publish'], [class*='release'], button:has-text('发表'), button:has-text('发布')"
            )
            return title is not None and publish is not None
        except Exception:
            return False

    async def confirm_publish(self, task_id: Optional[str] = None) -> dict:
        """Confirm a pending publish by clicking publish on the prepared tab.

        优先复用 publish() 阶段缓存且已填好表单的 tab；若缓存失效（worker
        重启/超时/页面关闭），则从 Redis payload 幂等重填后再点击发布（R13/R18），
        最后退化为重新打开创作中心尽力点击发布。
        """
        # 1. 复用缓存的待确认 tab
        entry = _pop_pending_tab(task_id) if task_id else None
        if entry:
            try:
                self.browser = entry["browser"]
                self.page = entry["page"]
                await self.page.bring_to_front()
                await self._click_publish()
                published_url, published_id = await self._wait_for_publish()
                # 发布后置顶神评（探活式，失败不阻断；从 Redis payload 取神评）
                await self._post_publish_comments_from_payload(task_id, published_url)
                await self._close_connection()
                return {
                    "success": True,
                    "published_url": published_url,
                    "published_id": published_id,
                }
            except PublishTimeoutError as e:
                # P0-1：发布结果未确认即失败，不 fallback（缓存 tab 即真实表单，
                # 再重开会造成重复发布/误发风险），直接返回失败交由 celery 判定 failed
                await self._close_connection()
                return {"success": False, "error": str(e), "timeout": True}
            except Exception as e:
                logger.error(f"Confirm publish via cached tab failed: {e}", exc_info=True)
                await self._close_connection()
                # 仅非超时异常才继续尝试 fallback


        # 2. fallback：从 Redis payload 幂等重填（R13/R18）后再点击发布
        pending = None
        if task_id:
            try:
                from app.services import multi_operator
                pending = await multi_operator.get_pending(task_id)
            except Exception:
                pending = None
        if pending:
            try:
                await self._connect()
                await self.page.goto(self.CREATOR_URL, wait_until="domcontentloaded")
                refilled = await self._refill_pending_form(pending, task_id=task_id)
                if not refilled:
                    await self._close_connection()
                    # R18：selector 不匹配已冻结，人工介入，0 误发
                    return {
                        "success": False,
                        "error": "selector_mismatch: form structure changed, pending frozen for manual intervention",
                    }
                await self._click_publish()
                published_url, published_id = await self._wait_for_publish()
                # 发布后置顶神评（探活式，失败不阻断；从 Redis payload 取神评）
                await self._post_publish_comments_from_payload(task_id, published_url)
                await self._close_connection()
                try:
                    await multi_operator.delete_pending(task_id)
                except Exception:
                    pass
                return {
                    "success": True,
                    "published_url": published_url,
                    "published_id": published_id,
                }
            except Exception as e:
                logger.error(f"Confirm publish via redis refill failed: {e}", exc_info=True)
                await self._close_connection()
                return {"success": False, "error": str(e)}

        # 3. 兜底：重新连接并打开创作中心尽力点击发布（一期旧行为）
        try:
            await self._connect()
            await self.page.goto(self.CREATOR_URL, wait_until="domcontentloaded")
            await self._click_publish()
            published_url, published_id = await self._wait_for_publish()
            # 发布后置顶神评（探活式，失败不阻断；从 Redis payload 取神评）
            await self._post_publish_comments_from_payload(task_id, published_url)
            await self._close_connection()
            return {
                "success": True,
                "published_url": published_url,
                "published_id": published_id,
            }
        except Exception as e:
            logger.error(f"Confirm publish failed: {e}", exc_info=True)
            await self._close_connection()
            return {"success": False, "error": str(e)}

    async def check_login_status(self) -> dict:
        """检查当前登录态是否有效。"""
        try:
            await self._connect()
            need_login = await self._need_login()
            await self._close_connection()
            return {
                "status": "expired" if need_login else "valid",
                "platform": self.PLATFORM,
            }
        except Exception as e:
            logger.error(f"Check login status failed: {e}", exc_info=True)
            await self._close_connection()
            return {"status": "error", "platform": self.PLATFORM, "error": str(e)}


class DouyinPublisher(VideoChannelPublisher):
    """Publisher for Douyin (抖音) platform."""

    PLATFORM = "douyin"
    CREATOR_URL = "https://creator.douyin.com/creator-micro/content/upload"
    # 抖音有独立话题框，话题不嵌进描述，走 `_set_tags` 独立写入
    EMBED_TAGS_IN_DESC = False

    async def _need_login(self) -> bool:
        """Check Douyin login state."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            login_selector = await self.page.query_selector(
                ".login-container, [class*='login']"
            )
            return login_selector is not None
        except Exception:
            return True

    async def _set_tags(self, tags: list):
        """Set Douyin-specific tags (话题)."""
        tag_input = await self.page.query_selector(
            "[class*='tag'] input, [placeholder*='话题']"
        )
        if tag_input:
            for tag in tags:
                await tag_input.fill(f"#{tag}")
                await asyncio.sleep(0.5)
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(0.3)


class KuaishouPublisher(VideoChannelPublisher):
    """Publisher for Kuaishou (快手) platform."""

    PLATFORM = "kuaishou"
    CREATOR_URL = "https://cp.kuaishou.com/article/publish/video"
    # 快手有独立话题框
    EMBED_TAGS_IN_DESC = False

    async def _need_login(self) -> bool:
        """Check Kuaishou login state."""
        try:
            await self.page.goto(self.CREATOR_URL, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            login_selector = await self.page.query_selector(
                "[class*='login'], .qr-login"
            )
            return login_selector is not None
        except Exception:
            return True


def get_publisher(platform: str, **kwargs) -> VideoChannelPublisher:
    """Factory function to get the appropriate publisher for a platform."""
    publishers = {
        "wechat_channel": VideoChannelPublisher,
        "douyin": DouyinPublisher,
        "kuaishou": KuaishouPublisher,
    }
    publisher_class = publishers.get(platform)
    if not publisher_class:
        raise ValueError(
            f"Unsupported platform: {platform}. Supported: {list(publishers.keys())}"
        )
    return publisher_class(**kwargs)
