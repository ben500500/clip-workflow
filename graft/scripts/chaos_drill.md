# scripts/chaos_drill.py · [[rpa-multi-operator-infrastructure]]

R21 混沌演练编排脚本，注入 Chromium 崩溃/Redis 重启/worker 重启三种故障并验证全链路自愈，作为上线前强制演练工具。

- _redis_get · function · L54-L56 — 创建 Redis 异步客户端连接，供各演练场景读写路由表与 profiles 数据。
- _get_route_states · function · L59-L70 — 扫描 pub:route:* 键并汇总各 account 的路由状态（status/port/fail_streak/heartbeat），供自愈观测与检查模式使用。
- _get_profiles · function · L73-L78 — 读取 pub:profiles 键并解析为 JSON 列表，用于校验 Redis 重启后 bootstrap 是否重建了 profiles。
- _run_cmd · function · L83-L88 — 执行 shell 命令并捕获返回码与输出，统一封装故障注入与容器操作的外部命令调用。
- inject_chromium_crash · function · L91-L102 — 通过 ps 匹配 user-data-dir 含指定 profile 的 Chromium 进程并 kill -9，模拟浏览器崩溃以触发 R12 失效识别。
- inject_redis_restart · function · L105-L108 — 通过 docker compose restart 重启 Redis 容器，模拟 Redis 故障以验证路由/配额重建。
- inject_worker_restart · function · L111-L116 — 通过 docker compose restart 重启指定 worker 容器，模拟 worker 故障以验证幂等恢复。
- _wait_ready · function · L121-L138 — 在窗口期内轮询路由表，等待达到预期自愈状态（全部 ready 或至少一个 expired），作为演练断言核心。
- drill_chromium · function · L141-L160 — 执行 Chromium 崩溃场景：注入崩溃后断言路由表在窗口内识别 expired，并观测 ready 恢复。
- drill_redis · function · L163-L197 — 执行 Redis 重启场景：重启前记录路由、重启后等待就绪并校验 profiles 被 bootstrap 重建。
- drill_worker · function · L200-L210 — 执行 worker 重启场景：重启容器并观测恢复，幂等性需人工结合日志核对。
- main · function · L215-L264 — 解析参数、分发各演练场景并汇总结果，按全部通过/部分失败/参数错误返回退出码 0/1/2。
