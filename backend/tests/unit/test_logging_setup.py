"""日志脱敏单测：第三方接口 key 在查询串里，不能顺着 INFO 日志漏进容器日志（11-09）。

钉三件事：
1. `redact_credentials` 只打敏感参数的值，参数名和其他查询参数留着（还要能看出是哪条链路）；
2. filter 挂在 handler 上并对 `%s` 插值后的最终文本生效（record.args 走的是 getMessage）；
3. `install_credential_redaction` 幂等，且把 httpx/httpcore 抬到 WARNING。

运行：cd backend && python -m pytest tests/unit/test_logging_setup.py -v
"""

import logging

from app.logging_setup import (
    SensitiveURLFilter,
    install_credential_redaction,
    redact_credentials,
)


def test_redact_masks_only_sensitive_values():
    url = "https://api.17zhiling.com/api/video-inference/task-status?key=SECRET123&taskId=t-456"
    out = redact_credentials(url)
    assert "SECRET123" not in out
    assert "key=***" in out
    assert "taskId=t-456" in out          # 任务号留着，排障还要用它对账


def test_redact_handles_multiple_and_padded_params():
    out = redact_credentials("GET https://x/y?a=1&key=K1&token=T1&z=3 200 OK")
    assert "key=K1" not in out and "token=T1" not in out
    assert "a=1" in out and "z=3" in out
    assert redact_credentials("") == ""
    assert redact_credentials("没有查询串的普通日志") == "没有查询串的普通日志"


def test_filter_redacts_interpolated_records():
    """日志里用 %s 拼 URL 是最常见的写法，脱敏必须在插值之后仍然拦得住。

    自己挂一个内存 handler（不用 caplog：caplog 的 handler 上没有我们的 filter，
    断言会变成「测了个寂寞」）。
    """
    lines = []

    class _Collect(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    handler = _Collect()
    handler.addFilter(SensitiveURLFilter())
    logger = logging.getLogger("unit.redact")
    saved = (list(logger.handlers), logger.propagate, logger.level)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)  # 不设就跟着 root（pytest 下常是 WARNING），INFO 直接不发
    try:
        logger.info("HTTP Request: GET %s", "https://api.17zhiling.com/x?key=SECRET999&taskId=t1")
    finally:
        logger.handlers, logger.propagate, logger.level = saved

    assert lines, "filter 不该把日志吞掉，只该改内容"
    assert "SECRET999" not in lines[0]
    assert "key=***" in lines[0] and "taskId=t1" in lines[0]


def test_install_is_idempotent_and_quiets_httpx():
    """用假 root（只要 .handlers）验幂等，不去动真实根 logger 的 handler 列表。"""

    class _FakeRoot:
        def __init__(self):
            self.handlers = [logging.StreamHandler()]

    fake = _FakeRoot()
    try:
        first = install_credential_redaction(root=fake)
        second = install_credential_redaction(root=fake)
        assert first["filters_added"] == 1
        assert second["filters_added"] == 0, "重复安装不许再挂一份 filter（同一条日志打码两遍没意义）"
        assert len(fake.handlers[0].filters) == 1
        for name in ("httpx", "httpcore", "urllib3"):
            assert logging.getLogger(name).level == logging.WARNING
    finally:
        for name in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(name).setLevel(logging.NOTSET)
