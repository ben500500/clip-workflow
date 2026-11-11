"""视频直链**形状闸门**（11-10 加）。

为什么要有这一层（163 现网实测，见 `docs/项目进度总览-20261109.md` 8-12）：
短剧导流页那类视频号分享链接，智令 doc/107「解析成功」回来的不是视频流，而是它
自己域名的**站点根**——实测三条链接（`sph/AJFwAUW6YY`／`ApyMKS6YYR`／`Ay5A62uDEu`）
全部回 `https://vnd2.17zhilian.cn/`。旧判据只写「字符串以 http 开头」，于是这个
首页地址被当直链一路收下，三个下游一起中招：

1. 下载原片把那个 10871 字节的 HTML（`<title>左下角剧名一口气免费看完大结局</title>`）
   存成「下载成功」（`AS-BB8563FD`，11-09 已按内容闸门改判 failed）；
2. 反推把这个非视频地址交给视频理解 → 必然「未检测到视频」→ 轮询 FAIL 且 errMsg 空
   → 库里只剩一句「任务处理失败」；
3. 自动补投按 `is_direct_video_url` 判它不是直链 → 再花 0.01 元解析一次 → 拿回同一个
   根路径，钱花了结果一样。

**为什么不按「路径必须带视频扩展名」那么严**：真实可用的直链里有一大类是分片／播放
入口（`finder.video.qq.com/live?sig=…`，见 `models.py` 对 `play_url` 的注释与
`tests/unit/test_wechat_dl_parse_cache.py`），路径本来就没扩展名；现网上传件的 75 条
成功 temp 直链倒是都带 `.mp4`，但按扩展名一刀切会把上面那类在用的链路判死。所以这里
只拦**形状上绝不可能是视频**的三类（站点根／网页文档／封面图），形状怪的真直链放过，
后面还有下载侧的内容闸门兜底。判据要窄不要宽，宽了就是今天这个事故。
"""

from typing import Optional
from urllib.parse import urlsplit

# 明显是网页文档的结尾（导流页最爱给 .html／.php 这类）
DOC_EXTS = (".html", ".htm", ".shtml", ".asp", ".aspx", ".jsp", ".php")
# 封面图直链特征（与 provider_registry._is_image_url、preview_client 同口径）
IMAGE_URL_HINTS = ("picformat", "wxampicformat")


def url_shape_text(url: Optional[str]) -> str:
    """给报错/日志用的 URL 摘要：只留 `scheme://host/path`，**签名查询串不带出去**。

    直链普遍带 `?sign=…&token=…`，这些是要防泄漏的东西；报错文本会进 `error` 列、
    会显示在界面上，所以宁可只给到路径。
    """
    try:
        p = urlsplit((url or "").strip())
    except ValueError:
        return "(无法解析的地址)"
    if not p.scheme and not p.netloc:
        return (url or "")[:120]
    return f"{p.scheme}://{p.netloc}{p.path}"


def direct_url_reject_reason(url: Optional[str]) -> Optional[str]:
    """能不能当「上游可直接拉流的视频地址」用。

    返回 `None`＝收下；返回字符串＝白话拒收原因（会直接进任务 error 给一线看，
    所以要写「这是什么＋下一步干什么」，不要写成技术黑话）。
    """
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return "解析回来的不是 http(s) 地址"
    path = (urlsplit(u).path or "").strip().lower()
    if path in ("", "/"):
        return (
            "解析回来的只有站点首页地址、没有任何视频路径——这类链接是短剧导流页，"
            "不是能拉流的视频；请改用可直接播放的链接，或把视频下载下来走「上传文件反推」"
        )
    if path.endswith(DOC_EXTS):
        return f"解析回来的是网页文件（{url_shape_text(u)}），不是视频地址"
    if any(hint in u.lower() for hint in IMAGE_URL_HINTS):
        return "解析回来的是封面图地址，不是视频地址"
    return None
