#!/usr/bin/env python3
"""多运营者 bootstrap：从 Redis 读取 `pub:profiles`，落盘到 /app/profiles.json。

供 supervisord 在启动 Chromium / cdp_proxy 前调用；rpa_worker 容器内不直连 DB，
profile 列表由 backend 的 sync_multi_operator_profiles beat 任务写入 Redis。

- 读取 `pub:profiles`（JSON 数组 [{profile_id, port, account_id, profile_dir, operator_id}]）
- 写 /app/profiles.json（同时生成 chrom_profiles 与 cdp_profiles 两个视图）
- 未开启多运营者或列表为空时，清空文件（让启动脚本回退一期单实例）
"""

import json
import os

REDIS_URL = os.getenv("REDIS_URL", "")
OUT = "/app/profiles.json"
KEY = "pub:profiles"


def main():
    profiles = []
    if REDIS_URL:
        try:
            import redis
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            raw = r.get(KEY)
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    profiles = parsed
        except Exception as e:
            print(f"[bootstrap] read profiles failed: {e}", flush=True)
            profiles = []

    payload = {
        "multi_operator": bool(profiles),
        "profiles": profiles,
        # chrom_profiles: start_chromium.sh 用
        "chrom_profiles": [
            {"profile_id": p.get("profile_id"), "port": int(p.get("port") or 9223),
             "profile_dir": p.get("profile_dir") or f"/data/chrome-profiles/{p.get('profile_id')}"}
            for p in profiles
        ],
        # cdp_profiles: cdp_proxy.py 多实例鉴权转发用（listen=port, target=port 同源）
        "cdp_profiles": [
            {"listen_port": int(p.get("port") or 9222), "target_port": int(p.get("port") or 9223),
             "account_id": p.get("account_id") or ""}
            for p in profiles
        ],
    }
    with open(OUT, "w") as f:
        json.dump(payload, f)
    print(f"[bootstrap] wrote {len(profiles)} profiles to {OUT}", flush=True)


if __name__ == "__main__":
    main()
