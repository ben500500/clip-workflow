"""日志脱敏：防止第三方接口的密钥顺着「请求 URL」漏进 docker logs。

起因（11-09 现网排查反推提示词时看到）：智令的 doc/119 轮询把账号 key 放在
**查询串**里（`GET /api/video-inference/task-status?key=<key>&taskId=<id>`），
而 `logging.basicConfig(level=INFO)` 之后 httpx 自带一条 INFO
「HTTP Request: GET https://api.17zhiling.com/...?key=<真 key> ... 200 OK」。
前端 4s 轮询一次 = 一天几十万次把密钥明文写进容器日志，`docker logs`、日志采集、
截图给外部排障的人，全都算泄露面。key 挪不出查询串（官方接口就这么定的），
所以在本机这一侧收口：

1. `httpx` / `httpcore` / `urllib3` 的 logger 抬到 WARNING —— 逐请求 INFO 行不再打；
2. 给根 logger 的每个 handler 挂 `SensitiveURLFilter` —— 就算别的库/我们自己的
   日志打了带 key 的 URL，也在落盘前替换成 `key=***`。

两条都做：只抬级别会漏掉「别的组件也打 URL」，只挂 filter 会留下海量无用的
逐请求 INFO。脱敏是纵深防御，不是唯一防线：密钥本身仍只走环境变量、不回显界面。
"""

import logging
import re
from typing import Iterable, Optional

# 需要打码的查询参数名（小写比对）。覆盖智令/企微后台/OSS 签名里会出现的敏感键。
SENSITIVE_PARAMS: tuple = (
    "key", "apikey", "api_key", "token", "access_token", "authorization",
    "password", "secret", "secret_key", "signature", "x-amz-signature",
    "x-amz-credential", "x-amz-security-token", "aivideo_auth",
)

_QUIET_LOGGERS: tuple = ("httpx", "httpcore", "urllib3", "asyncio")

# ?key=abc&x=1 / &key=abc / ?key=abc（到 & 或空白或引号或行尾为止）
_PATTERN = re.compile(
    r"(?P<sep>[?&])(?P<name>" + "|".join(re.escape(p) for p in SENSITIVE_PARAMS) + r")=(?P<val>[^\s&\"']*)",
    re.IGNORECASE,
)


def redact_credentials(text: str) -> str:
    """把 URL 查询串里的敏感参数值替换成 ***，参数名保留（便于看出是哪条链路）。"""
    if not text:
        return text
    return _PATTERN.sub(lambda m: f"{m.group('sep')}{m.group('name')}=***", text)


class SensitiveURLFilter(logging.Filter):
    """落盘前打码。挂 handler 而不是 logger：子 logger 的 record 会向上冒泡到根 handler。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - 格式化本身坏了就不该在这里再炸一次
            return True
        redacted = redact_credentials(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install_credential_redaction(
    loggers: Iterable[str] = _QUIET_LOGGERS,
    level: int = logging.WARNING,
    root: Optional[logging.Logger] = None,
) -> dict:
    """幂等安装：抬级别 + 挂打码 filter。返回实际调整了什么，供启动日志与测试核对。

    在 `logging.basicConfig(...)` 之后调用才有 handler 可挂（main.py 里就是这个顺序）。
    """
    root = root if root is not None else logging.getLogger()
    for name in loggers:
        logging.getLogger(name).setLevel(level)

    added = 0
    for handler in list(root.handlers):
        if any(isinstance(f, SensitiveURLFilter) for f in handler.filters):
            continue
        handler.addFilter(SensitiveURLFilter())
        added += 1
    return {"quieted": list(loggers), "filters_added": added}
