#!/usr/bin/env python3
"""部署后登录端到端冒烟 —— 零 sleep 立即打受保护接口（Issue #350 回归网）。

用法（在 163 的后端容器内跑，脚本从 stdin 送进去）：

    ssh cc12703@192.168.1.163 'docker exec -i clip-backend python -' < scripts/smoke_deploy.py

或走 nginx 从外部跑：改 BASE 为 http://192.168.1.163 后直接在本机执行。

⚠️ 端口坑：后端容器内 **监听 8080**。`backend/Dockerfile` 里的 `EXPOSE 8000`
   是误导性遗留，真实 CMD 是 `uvicorn ... --port 8080`。写 8000 会得到一串
   `status=-1`（连接被拒），别误判成「服务挂了」。

基线：8 passed / 0 failed。任一项 FAIL 即视为部署回归，须查 `/api/auth/me` 的
      登录竞态（`login()` 是否在 return 前显式 `await db.commit()`）。
"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"
OK = FAIL = 0


def call(method, path, body=None, token=None, timeout=15):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # 连接错误 → -1，配合下面 detail 打印便于定位端口问题
        return -1, repr(e)


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [PASS] {name} {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


print("=== 1) 登录 admin/admin123 ===")
st, body = call("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
check("login 200", st == 200, f"status={st} body={body[:120]}")
tok = None
try:
    tok = json.loads(body).get("access_token")
except Exception:
    pass
check("拿到 access_token", bool(tok), f"len={len(tok) if tok else 0}")

# ── 关键：#350 时序修复。登录返回后 0 延迟立刻打受保护接口 ──
print("=== 2) 零 sleep 立刻 GET /api/auth/me（#350 回归）===")
st, body = call("GET", "/api/auth/me", token=tok)
check("me 200 无竞态", st == 200, f"status={st}")
try:
    u = json.loads(body)
    check("me 返回 admin", u.get("username") == "admin", f"username={u.get('username')}")
except Exception as e:
    check("me 可解析", False, repr(e))

print("=== 3) 重复调用稳定性 ===")
sts = [call("GET", "/api/auth/me", token=tok)[0] for _ in range(3)]
check("3 连击全 200", sts == [200, 200, 200], f"statuses={sts}")

print("=== 4) 未带 token 必须 401 ===")
st, _ = call("GET", "/api/auth/me")
check("匿名 me 401", st == 401, f"status={st}")

print("=== 5) 受保护业务接口（/api/auth/users 需管理员）===")
st, _ = call("GET", "/api/auth/users", token=tok)
check("带 token 业务接口 200", st == 200, f"status={st}")
st2, _ = call("GET", "/api/auth/users")
check("匿名业务接口 401", st2 == 401, f"status={st2}")

print(f"\n=== 结果: {OK} passed / {FAIL} failed ===")
raise SystemExit(0 if FAIL == 0 else 1)
