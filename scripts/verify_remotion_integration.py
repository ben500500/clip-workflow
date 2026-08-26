#!/usr/bin/env python3
"""Remotion 混剪增强（P2 T11）集成验证脚本。

静态验证 P2（T6-T11）各环节是否就位，无 DB/Redis 依赖：
1. alembic migration 存在（0046 remotion_mix_config + 0047 remotion_result 列）；
2. Celery beat schedule 配置正确（remotion 队列 + remotion-stale-recovery 条目）；
3. Worker service 在 compose 中定义（worker-remotion + clip-remotion-worker 镜像）；
4. API 路由注册（remotion router 暴露 status/render 端点）。

用法：
    python3 scripts/verify_remotion_integration.py
    # 或指定 backend 根目录（默认为脚本同级的 ../backend）
    python3 scripts/verify_remotion_integration.py --backend /path/to/backend
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 期望的 alembic 迁移文件（相对 alembic/versions）
EXPECTED_MIGRATIONS = [
    "0046_slice_task_remotion_mix.py",
    "0047_slice_task_remotion_result.py",
]

# 期望的 celery beat 条目（remotion 守护）
EXPECTED_BEAT_ENTRY = "remotion-stale-recovery"
# 期望的 remotion 队列名
EXPECTED_QUEUE = "remotion"
# 期望的 compose service 与镜像
EXPECTED_COMPOSE_SERVICE = "worker-remotion"
EXPECTED_COMPOSE_IMAGE = "clip-remotion-worker:latest"
# 期望的 API 路由
EXPECTED_API_PATHS = [
    "/v1/remotion/status/{slice_task_id}",
    "/v1/remotion/render/{slice_task_id}",
]


def _fail(msg: str, *details: str) -> None:
    print(f"  [FAIL] {msg}")
    for d in details:
        print(f"         {d}")


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def check_migrations() -> bool:
    print("[1] alembic migration 存在性")
    versions = REPO_ROOT / "alembic" / "versions"
    ok = True
    for name in EXPECTED_MIGRATIONS:
        if (versions / name).is_file():
            _ok(f"迁移 {name} 存在")
        else:
            _fail(f"迁移 {name} 缺失", f"期望路径: {versions / name}")
            ok = False
    # 链单一 head 校验（0047 应为唯一 head）
    try:
        import alembic.config
        from alembic.script import ScriptDirectory

        cfg = alembic.config.Config(str(REPO_ROOT / "alembic" / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        heads = ScriptDirectory.from_config(cfg).get_heads()
        if heads == ["0047_slice_task_remotion_result"]:
            _ok("alembic 迁移链单一 head = 0047_slice_task_remotion_result")
        else:
            _fail("alembic head 非预期", f"实际 heads: {heads}")
            ok = False
    except Exception as e:
        _fail(f"alembic 链校验异常: {e}")
        ok = False
    return ok


def check_celery() -> bool:
    print("[2] Celery beat schedule 与队列")
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    try:
        from app.celery.tasks import celery_app

        ok = True
        queues = set(celery_app.conf.task_queues.keys())
        if EXPECTED_QUEUE in queues:
            _ok(f"remotion 队列已定义: {EXPECTED_QUEUE}")
        else:
            _fail(f"队列缺失: {EXPECTED_QUEUE}", f"当前队列: {sorted(queues)}")
            ok = False

        beat = celery_app.conf.beat_schedule
        if EXPECTED_BEAT_ENTRY in beat:
            task = beat[EXPECTED_BEAT_ENTRY]["task"]
            if task == "app.celery.remotion_tasks.remotion_stale_recovery_task":
                _ok(f"beat 条目 {EXPECTED_BEAT_ENTRY} → {task}")
            else:
                _fail(f"beat 条目任务名不匹配: {task}")
                ok = False
        else:
            _fail(f"beat 条目缺失: {EXPECTED_BEAT_ENTRY}", f"当前条目: {sorted(beat.keys())}")
            ok = False

        routes = celery_app.conf.task_routes
        if routes.get("app.celery.remotion_tasks.run_remotion_mix_task") == {"queue": "remotion"}:
            _ok("run_remotion_mix_task 路由到 remotion 队列")
        else:
            _fail("run_remotion_mix_task 路由未正确配置")
            ok = False
        return ok
    except Exception as e:
        _fail(f"Celery 配置加载异常: {e}")
        return False


def check_compose() -> bool:
    print("[3] docker-compose worker-remotion")
    compose = REPO_ROOT / "docker-compose.yml"
    if not compose.is_file():
        _fail("docker-compose.yml 不存在")
        return False
    text = compose.read_text(encoding="utf-8")
    ok = True
    if f"  {EXPECTED_COMPOSE_SERVICE}:" in text:
        _ok(f"compose 定义 service: {EXPECTED_COMPOSE_SERVICE}")
    else:
        _fail(f"compose 缺少 service: {EXPECTED_COMPOSE_SERVICE}")
        ok = False
    if EXPECTED_COMPOSE_IMAGE in text:
        _ok(f"compose 使用镜像: {EXPECTED_COMPOSE_IMAGE}")
    else:
        _fail(f"compose 未引用镜像: {EXPECTED_COMPOSE_IMAGE}")
        ok = False
    # 校验镜像 Dockerfile 存在
    dockerfile = REPO_ROOT / "docker" / "remotion-worker" / "Dockerfile"
    if dockerfile.is_file():
        _ok("docker/remotion-worker/Dockerfile 存在")
    else:
        _fail("docker/remotion-worker/Dockerfile 缺失")
        ok = False
    return ok


def check_api() -> bool:
    print("[4] API 路由注册")
    remotion_py = REPO_ROOT / "backend" / "app" / "api" / "remotion.py"
    main_py = REPO_ROOT / "backend" / "app" / "main.py"
    ok = True
    if remotion_py.is_file():
        src = remotion_py.read_text(encoding="utf-8")
        for p in EXPECTED_API_PATHS:
            if p in src:
                _ok(f"remotion.py 定义路由 {p}")
            else:
                _fail(f"remotion.py 缺少路由 {p}")
                ok = False
    else:
        _fail("backend/app/api/remotion.py 缺失")
        ok = False

    if main_py.is_file():
        main_src = main_py.read_text(encoding="utf-8")
        if "remotion" in main_src and "_protected_routers" in main_src:
            _ok("main.py 注册 remotion 到 protected routers")
        else:
            _fail("main.py 未注册 remotion 路由")
            ok = False
    else:
        _fail("backend/app/main.py 缺失")
        ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Remotion 混剪增强 P2 集成验证")
    parser.add_argument("--backend", help="backend 目录（默认 ../backend）")
    args = parser.parse_args()
    if args.backend:
        sys.path.insert(0, str(Path(args.backend).resolve()))

    print("Remotion 混剪增强（P2 T6-T11）集成验证\n" + "=" * 50)
    results = [
        check_migrations(),
        check_celery(),
        check_compose(),
        check_api(),
    ]
    passed = sum(1 for r in results if r)
    print("=" * 50)
    print(f"验证完成: {passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
