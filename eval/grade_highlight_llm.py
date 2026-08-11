#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clip-workflow 高光选择 LLM 轻量评测器
======================================
针对 AutoClip 的两步核心 LLM 调用做端到端评测：
  - step2 时间点 (timeline)：outline + SRT -> 带 start/end 的片段 JSON
  - step3 评分 (scoring)：片段 -> final_score + recommend_reason

零外部依赖：仅用 Python 标准库；真实调用走 DashScope OpenAI 兼容接口。

用法：
  # 1) 干跑（不调 API，用黄金答案当预测，验证评分逻辑）
  python3 grade_highlight_llm.py --dry-run

  # 2) 实跑（需 DASHSCOPE_API_KEY 环境变量）
  export DASHSCOPE_API_KEY=sk-xxxx
  python3 grade_highlight_llm.py --model qwen-plus

  # 可选：指定评测集 / 输出报告
  python3 grade_highlight_llm.py --cases eval_cases.json --report eval_report.json
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def time_to_seconds(s: str) -> float:
    """'HH:MM:SS,mmm' -> 秒（浮点）。也兼容 'HH:MM:SS.mmm'。"""
    if not s:
        return 0.0
    s = s.strip().replace(",", ".")
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$", s)
    if not m:
        return 0.0
    h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3))
    ms = m.group(4) or "0"
    ms = int(ms.ljust(3, "0"))
    return h * 3600 + mi * 60 + se + ms / 1000.0


def srt_block_end(srt_text: str) -> float:
    """取 SRT 文本里最大的结束时间戳（秒）。"""
    ends = re.findall(r"-->\\s*(\\d{2}:\\d{2}:\\d{2}[,.]\\d{1,3})", srt_text)
    if not ends:
        ends = re.findall(r"-->\\s*(\\d{2}:\\d{2}:\\d{2})", srt_text)
    secs = [time_to_seconds(e) for e in ends]
    return max(secs) if secs else 0.0


def load_prompt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_json(text: str):
    """从模型输出里抠出第一个 JSON 数组/对象。"""
    if text is None:
        return None
    text = text.strip()
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # 优先找数组
    s = text.find("[")
    e = text.rfind("]")
    if s != -1 and e != -1 and e > s:
        cand = text[s : e + 1]
        try:
            return json.loads(cand)
        except Exception:
            pass
    # 退而求其次找对象
    s = text.find("{")
    e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        cand = text[s : e + 1]
        try:
            return json.loads(cand)
        except Exception:
            pass
    return None


# ----------------------------------------------------------------------------
# 模型调用（DashScope OpenAI 兼容模式，零依赖）
# ----------------------------------------------------------------------------
def call_llm(prompt_text: str, input_obj, model: str, api_key: str, temperature: float = 0.2):
    system = "你是顶级的视频内容分析师，严格按照用户指令输出 JSON。"
    user = prompt_text + "\n\n输入数据：\n" + json.dumps(input_obj, ensure_ascii=False)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"} if False else None,
    }
    body = {k: v for k, v in body.items() if v is not None}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"]


# ----------------------------------------------------------------------------
# 评分逻辑
# ----------------------------------------------------------------------------
def iou(a_s, a_e, b_s, b_e):
    inter = max(0.0, min(a_e, b_e) - max(a_s, b_s))
    union = max(a_e, b_e) - min(a_s, b_s)
    return inter / union if union > 0 else 0.0


def grade_timeline(case, pred, cfg):
    MIN = cfg["duration"]["min_seconds"]
    MAX = cfg["duration"]["max_seconds"]
    TOL = cfg.get("time_tolerance_seconds", 10)
    gold = case["gold"]["timeline"]
    srt = case["srt_text"]
    block_end = srt_block_end(srt)

    result = {"format_ok": False, "coverage": 0.0, "time_tol_rate": 0.0,
              "duration_violations": 0, "endpoint_pass_rate": 0.0,
              "avg_iou": 0.0, "score": 0.0, "detail": []}

    if not isinstance(pred, list) or not pred:
        result["detail"].append("预测不是非空 JSON 数组")
        return result
    # 必要字段
    valid = [p for p in pred if all(k in p for k in ("outline", "start_time", "end_time"))]
    result["format_ok"] = len(valid) == len(pred) and len(pred) > 0

    # 为每个 gold 找最佳匹配（按 IoU）
    matched = 0
    tol_pass = 0
    ious = []
    endpoint_pass = 0
    endpoint_total = 0
    for g in gold:
        gs, ge = time_to_seconds(g["start_time"]), time_to_seconds(g["end_time"])
        best = None
        best_iou = -1
        for p in valid:
            ps, pe = time_to_seconds(p["start_time"]), time_to_seconds(p["end_time"])
            ov = iou(gs, ge, ps, pe)
            if ov > best_iou:
                best_iou = ov
                best = (ps, pe)
        if best is None:
            continue
        ps, pe = best
        ious.append(max(0.0, best_iou))
        if best_iou > 0.1:
            matched += 1
        if abs(ps - gs) <= TOL and abs(pe - ge) <= TOL:
            tol_pass += 1
        # 端点语义
        if ge < block_end - 5:
            endpoint_total += 1
            if pe <= block_end - 1:  # 没有把 end 无脑顶到块尾
                endpoint_pass += 1
        elif abs(ge - block_end) <= TOL:  # T04：允许等于块尾
            endpoint_total += 1
            if abs(pe - block_end) <= TOL:
                endpoint_pass += 1

    result["coverage"] = matched / len(gold) if gold else 0.0
    result["time_tol_rate"] = tol_pass / len(gold) if gold else 0.0
    result["avg_iou"] = sum(ious) / len(ious) if ious else 0.0
    result["endpoint_pass_rate"] = endpoint_pass / endpoint_total if endpoint_total else 1.0

    # 时长约束（针对所有预测片段）
    for p in valid:
        ps, pe = time_to_seconds(p["start_time"]), time_to_seconds(p["end_time"])
        dur = pe - ps
        if dur < MIN or dur > MAX:
            result["duration_violations"] += 1
    dur_rate = 1.0 - (result["duration_violations"] / len(valid) if valid else 0.0)

    # 综合分
    score = (
        0.35 * result["coverage"]
        + 0.25 * result["time_tol_rate"]
        + 0.20 * dur_rate
        + 0.20 * result["endpoint_pass_rate"]
    )
    result["score"] = round(score, 3)
    result["detail"].append(
        f"覆盖 {matched}/{len(gold)}，时间容差通过 {tol_pass}/{len(gold)}，"
        f"时长违规 {result['duration_violations']} 段，端点 {endpoint_pass}/{endpoint_total}"
    )
    return result


def grade_scoring(case, pred, cfg):
    gold = case["gold"]
    expect_order = gold.get("expect_order", [])
    result = {"format_ok": False, "scale_error": False, "monotonicity": 0.0,
              "reason_ok_rate": 0.0, "score": 0.0, "detail": []}

    if not isinstance(pred, list) or not pred:
        result["detail"].append("预测不是非空 JSON 数组")
        return result
    valid = [p for p in pred if "final_score" in p and "recommend_reason" in p]
    result["format_ok"] = len(valid) == len(pred)

    # 尺度检查：0-1 约定，任何 >1.5 视为误用 0-100
    scores = [float(p["final_score"]) for p in valid if _is_num(p.get("final_score"))]
    if scores and max(scores) > 1.5:
        result["scale_error"] = True
        result["detail"].append(f"⚠️ 分数尺度疑似 0-100（最大值 {max(scores)}），与 0-1 约定冲突")
    # 落在 0-1 之外（<0 或 >1 但 <1.5）也算异常
    oob = [s for s in scores if s < 0 or s > 1.0]
    if oob:
        result["detail"].append(f"分数超出 [0,1]：{oob}")

    # 单调性：gold 期望顺序 vs 预测按分数降序
    if expect_order and valid:
        by_score = sorted(valid, key=lambda x: float(x["final_score"]), reverse=True)
        pred_order = [p.get("outline") for p in by_score]
        # 把 expect_order 转成标题列表（outline 可能是字符串或 dict）
        exp_titles = []
        for t in expect_order:
            exp_titles.append(t)
        # 计算保留的配对比例
        pairs = [(a, b) for i, a in enumerate(exp_titles) for b in exp_titles[i + 1:]]
        ok = 0
        for a, b in pairs:
            try:
                if pred_order.index(a) < pred_order.index(b):
                    ok += 1
            except ValueError:
                pass
        result["monotonicity"] = ok / len(pairs) if pairs else 1.0

    # 推荐语长度 8-40 字
    ok_reason = 0
    for p in valid:
        r = p.get("recommend_reason", "")
        if 8 <= len(r) <= 40:
            ok_reason += 1
    result["reason_ok_rate"] = ok_reason / len(valid) if valid else 0.0

    score = (
        0.30 * (1.0 if result["format_ok"] else 0.0)
        + 0.30 * result["monotonicity"]
        + 0.20 * (0.0 if result["scale_error"] else 1.0)
        + 0.20 * result["reason_ok_rate"]
    )
    result["score"] = round(score, 3)
    result["detail"].append(
        f"格式{'OK' if result['format_ok'] else 'FAIL'}，单调性 {result['monotonicity']:.2f}，"
        f"推荐语合规 {result['reason_ok_rate']:.2f}"
    )
    return result


def _is_num(x):
    try:
        float(x)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=os.path.join(HERE, "eval_cases.json"))
    ap.add_argument("--report", default=os.path.join(HERE, "eval_report.json"))
    ap.add_argument("--model", default="qwen-plus")
    ap.add_argument("--dry-run", action="store_true", help="不调 API，用黄金答案当预测验证评分逻辑")
    args = ap.parse_args()

    with open(args.cases, "r", encoding="utf-8") as f:
        data = json.load(f)
    cfg = data.get("meta", {})
    cases = data["cases"]
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    timeline_prompt = load_prompt(os.path.join(HERE, "prompts", "时间点.txt"))
    scoring_prompt = load_prompt(os.path.join(HERE, "prompts", "推荐理由.txt"))

    print(f"== clip-workflow 高光选择 LLM 评测 ==")
    print(f"模式: {'DRY-RUN(黄金答案自测)' if args.dry_run else '实跑模型=' + args.model}")
    print(f"用例数: {len(cases)}\n")

    report = {"model": "gold(dry-run)" if args.dry_run else args.model, "cases": []}
    total = 0.0
    for case in cases:
        ctype = case["type"]
        print(f"[{case['id']}] {case['name']}  ({ctype})")
        if args.dry_run:
            pred = case["gold"].get("timeline") or case["gold"].get("scores")
        else:
            if not api_key:
                print("  ✗ 缺少 DASHSCOPE_API_KEY 环境变量，无法实跑。用 --dry-run 验证评分逻辑。")
                return
            try:
                if ctype == "timeline":
                    inp = {"outline": case["outline"], "srt_text": case["srt_text"]}
                    raw = call_llm(timeline_prompt, inp, args.model, api_key)
                else:
                    inp = case["clips"]
                    raw = call_llm(scoring_prompt, inp, args.model, api_key)
                pred = extract_json(raw)
            except Exception as e:
                print(f"  ✗ 调用失败: {e}")
                continue

        if ctype == "timeline":
            res = grade_timeline(case, pred, cfg)
        else:
            res = grade_scoring(case, pred, cfg)
        total += res["score"]
        mark = "✓" if res["score"] >= 0.8 else ("△" if res["score"] >= 0.6 else "✗")
        print(f"  {mark} 得分 {res['score']:.2f}  | {'; '.join(res['detail'])}")
        report["cases"].append({"id": case["id"], "name": case["name"], "type": ctype, **res})

    overall = total / len(cases) if cases else 0.0
    print(f"\n== 总评: {overall:.2f} / 1.00 ==")
    print("评分参考: ≥0.80 优秀 / 0.60-0.79 可用 / <0.60 需调优")
    report["overall"] = round(overall, 3)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告已写: {args.report}")


if __name__ == "__main__":
    main()
