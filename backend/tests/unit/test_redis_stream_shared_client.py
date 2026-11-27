import asyncio

import pytest

from app.services import redis_stream


class _SharedRedis:
    def __init__(self):
        self.close_calls = 0
        self.rpush_calls = 0
        self.publish_calls = 0

    async def rpush(self, key, value):
        self.rpush_calls += 1
        await asyncio.sleep(0)
        return self.rpush_calls

    async def publish(self, channel, value):
        self.publish_calls += 1
        await asyncio.sleep(0)
        return self.publish_calls

    async def llen(self, key):
        await asyncio.sleep(0)
        return 0

    async def close(self):
        self.close_calls += 1
        raise AssertionError("shared Redis client must not be closed by request helpers")


@pytest.mark.asyncio
async def test_concurrent_node_queue_calls_keep_shared_client_open(monkeypatch):
    shared = _SharedRedis()
    monkeypatch.setattr(redis_stream, "get_redis", lambda: asyncio.sleep(0, result=shared))

    results = await asyncio.gather(*(
        redis_stream._publish_to_node_queue(
            f"node-{i}", {"task_id": f"task-{i}"}
        )
        for i in range(64)
    ))

    assert results == ["direct"] * 64
    assert shared.rpush_calls == 64
    assert shared.publish_calls == 64
    assert shared.close_calls == 0


@pytest.mark.asyncio
async def test_node_queue_observers_do_not_close_shared_client(monkeypatch):
    shared = _SharedRedis()
    monkeypatch.setattr(redis_stream, "get_redis", lambda: asyncio.sleep(0, result=shared))

    assert await redis_stream.get_node_queue_len("node-a") == 0
    assert await redis_stream.wake_node("node-a") is True
    assert shared.close_calls == 0
