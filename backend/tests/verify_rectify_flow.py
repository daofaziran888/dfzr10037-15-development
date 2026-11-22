"""跨报告合并重复发现 · 验收脚本（仅依赖标准库）。

用法：先启动后端（./run.sh，需是全新进程以保证内存数据干净），再执行：

    .venv/bin/python tests/verify_rectify_flow.py [base_url]

覆盖验收场景：
1. 审计员多选多份报告的关系样本，批量归并成整改批次证据；
2. 同一边号但未受影响图代的样本不被划入整改；
3. 整组派工后同步治理待办，生成可依证据分批领取的整改项，且可回看原报告与抽样依据；
4. 先在第一份报告确认修复 R7 断链并交付回执，实际核销的报告样本随回执回传；
5. 随后再交付同一回执：只核销一次，第二份报告的误连仍可领取；
6. 并发交付同一回执只核销一次；
7. 回执可按图代限定核销范围（先定断链所在版本）。
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")

PASSED = 0


def api(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    if "?" in path:
        path, query = path.split("?", 1)
        pairs = urllib.parse.parse_qsl(query)
        path = f"{path}?{urllib.parse.urlencode(pairs)}"
    req = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(label: str, cond: bool, detail: object = "") -> None:
    global PASSED
    assert cond, f"FAILED: {label} -> {detail}"
    PASSED += 1
    print(f"  ✓ {label}")


def main() -> None:
    health = api("GET", "/api/health")
    check("后端健康检查", health.get("ok") is True, health)

    print("[1] 关系样本池：R7 在两份报告中的冲突判断 + 未受影响图代")
    samples = api("GET", "/api/quality_audit/samples?边号=R7")["items"]
    by_code = {s["样本编号"]: s for s in samples}
    check("R7 样本共 3 个", len(samples) == 3, samples)
    check("QUAL-0001 记 R7 断链（全量扫描）",
          by_code["SAMP-0001"]["错误类型"] == "断链" and by_code["SAMP-0001"]["抽样口径"] == "全量扫描")
    check("QUAL-0002 另一口径记 R7 误连（抽样复核）",
          by_code["SAMP-0002"]["错误类型"] == "误连" and by_code["SAMP-0002"]["抽样口径"] == "抽样复核")
    check("SAMP-0003 属未受影响图代 G4", by_code["SAMP-0003"]["图代"] == "G4")

    print("[2] 多选两份报告的样本，归并成整改批次证据")
    merged = api("POST", "/api/quality_audit/batches/merge",
                 {"样本编号": ["SAMP-0001", "SAMP-0002"], "处理人": "审计员甲"})
    check("归并成功", merged["ok"], merged)
    batch = merged["batch"]
    check("批次标记冲突判断", batch["冲突标记"] is True and batch["错误类型"] == ["断链", "误连"])
    check("批次涉及两份报告", batch["涉及报告"] == ["QUAL-0001", "QUAL-0002"])
    check("批次只含选中的 2 个样本",
          [s["样本编号"] for s in batch["样本列表"]] == ["SAMP-0001", "SAMP-0002"])
    batch_code = batch["批次编号"]

    after = {s["样本编号"]: s for s in api("GET", "/api/quality_audit/samples?边号=R7")["items"]}
    check("未受影响图代 G4 的样本未被划入整改",
          after["SAMP-0003"]["状态"] == "待归并" and after["SAMP-0003"]["批次编号"] == "")

    print("[3] 整组派工：同步治理待办，生成可分批领取的整改项")
    dispatched = api("POST", f"/api/quality_audit/batches/{batch_code}/dispatch", {"处理人": "处理人乙"})
    check("派工成功", dispatched["ok"], dispatched)
    items = dispatched["items"]
    check("按错误类型生成 2 个整改项", [i["错误类型"] for i in items] == ["断链", "误连"], items)
    check("整改项均可领取", all(i["状态"] == "待领取" for i in items))
    detail = api("GET", f"/api/quality_audit/batches/{batch_code}")["batch"]
    trace = {s["样本编号"]: (s["报告编号"], s["抽样口径"]) for s in detail["样本列表"]}
    check("派工后可回看各自原报告和抽样依据",
          trace == {"SAMP-0001": ("QUAL-0001", "全量扫描"),
                    "SAMP-0002": ("QUAL-0002", "抽样复核")}, trace)

    duanlian = next(i for i in items if i["错误类型"] == "断链")
    wulian = next(i for i in items if i["错误类型"] == "误连")
    claimed = api("POST", f"/api/govern_dash/rectify-items/{duanlian['项编号']}/claim",
                  {"处理人": "处理人乙"})
    check("领取断链整改项", claimed["ok"] and claimed["item"]["状态"] == "整改中", claimed)

    print("[4] 先在第一份报告确认修复 R7 断链，交付修正回执")
    first = api("POST", "/api/govern_dash/rectify-receipts",
                {"回执编号": "RCPT-0001", "边号": "R7", "错误类型": ["断链"],
                 "图代": "G3", "处理人": "处理人乙", "说明": "已修复断链"})
    check("回执受理", first["ok"], first)
    written = first["receipt"]["本次核销样本"]
    check("实际核销的报告样本只有 QUAL-0001 的断链样本",
          [(s["样本编号"], s["报告编号"], s["错误类型"]) for s in written]
          == [("SAMP-0001", "QUAL-0001", "断链")], written)
    check("写回分清实际处理的关系错误类型", first["receipt"]["错误类型"] == ["断链"])

    print("[5] 随后再交付同一回执：只核销一次，误连仍可领取")
    again = api("POST", "/api/govern_dash/rectify-receipts",
                {"回执编号": "RCPT-0001", "边号": "R7", "错误类型": ["断链"],
                 "图代": "G3", "处理人": "处理人乙"})
    check("重复回执仍返回成功但不再核销",
          again["ok"] and again["receipt"]["重复回执"] is True
          and again["receipt"]["本次核销样本"] == [], again)
    check("累计核销样本仍只有首次的 SAMP-0001",
          [s["样本编号"] for s in again["receipt"]["核销样本"]] == ["SAMP-0001"])
    remaining = {r["项编号"]: r for r in again["剩余待整改"]}
    check("第二份报告的误连仍可领取",
          remaining.get(wulian["项编号"], {}).get("状态") == "待领取", remaining)
    receipts = api("GET", "/api/govern_dash/rectify-receipts")["items"]
    check("回执台账只有一条 RCPT-0001",
          sum(1 for r in receipts if r["回执编号"] == "RCPT-0001") == 1, receipts)
    samples_now = {s["样本编号"]: s for s in api("GET", "/api/quality_audit/samples?边号=R7")["items"]}
    check("断链样本已核销并登记回执",
          samples_now["SAMP-0001"]["状态"] == "已核销"
          and samples_now["SAMP-0001"]["核销回执"] == "RCPT-0001")
    check("误连样本仍在整改中（未核销）", samples_now["SAMP-0002"]["状态"] == "已归并")
    check("G4 图代样本始终未受影响", samples_now["SAMP-0003"]["状态"] == "待归并")
    batch_now = api("GET", f"/api/quality_audit/batches/{batch_code}")["batch"]
    check("批次写回为部分核销", batch_now["状态"] == "部分核销", batch_now["状态"])

    print("[6] 并发提交同一修正回执只核销一次（R9 一次修正断链+误连两项）")
    api("POST", "/api/quality_audit/batches/merge",
        {"样本编号": ["SAMP-0004", "SAMP-0005"], "处理人": "审计员甲"})
    api("POST", "/api/quality_audit/batches/BATCH-0002/dispatch", {"处理人": "处理人丙"})
    barrier = threading.Barrier(8)
    outcomes: list[dict] = []

    def fire() -> None:
        barrier.wait()
        outcomes.append(api("POST", "/api/govern_dash/rectify-receipts",
                            {"回执编号": "RCPT-CONC", "边号": "R9",
                             "错误类型": ["断链", "误连"], "处理人": "处理人丙"}))

    threads = [threading.Thread(target=fire) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fresh = [o for o in outcomes if o["receipt"]["重复回执"] is False]
    dups = [o for o in outcomes if o["receipt"]["重复回执"] is True]
    check("8 路并发只有 1 次真正核销", len(fresh) == 1 and len(dups) == 7,
          [(o["receipt"]["重复回执"], len(o["receipt"]["本次核销样本"])) for o in outcomes])
    check("该次核销了断链+误连两个样本",
          sorted(s["样本编号"] for s in fresh[0]["receipt"]["本次核销样本"])
          == ["SAMP-0004", "SAMP-0005"], fresh)
    check("重复交付均未新增核销", all(o["receipt"]["本次核销样本"] == [] for o in dups))
    r9 = {s["样本编号"]: s for s in api("GET", "/api/quality_audit/samples?边号=R9")["items"]}
    check("两个样本都只核销一次并登记同一回执",
          all(s["状态"] == "已核销" and s["核销回执"] == "RCPT-CONC" for s in r9.values()), r9)

    print("[7] 先定断链所在版本：回执按图代限定核销范围（R8）")
    api("POST", "/api/quality_audit/batches/merge",
        {"样本编号": ["SAMP-0006", "SAMP-0007"], "处理人": "审计员甲"})
    api("POST", "/api/quality_audit/batches/BATCH-0003/dispatch", {"处理人": "处理人丁"})
    scoped = api("POST", "/api/govern_dash/rectify-receipts",
                 {"回执编号": "RCPT-G3", "边号": "R8", "错误类型": "断链",
                  "图代": "G3", "处理人": "处理人丁"})
    check("只核销 G3 图代的断链样本",
          [s["样本编号"] for s in scoped["receipt"]["本次核销样本"]] == ["SAMP-0007"], scoped)
    r8 = {s["样本编号"]: s for s in api("GET", "/api/quality_audit/samples?边号=R8")["items"]}
    check("G4 图代样本未被划入本次核销", r8["SAMP-0006"]["状态"] == "已归并", r8)

    print(f"\n全部 {PASSED} 项验收通过 ✅")


if __name__ == "__main__":
    main()
