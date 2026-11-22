"""治理看板领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。

治理待办整改：用质量审计同步来的整改批次证据生成可分批领取的整改项，
处理人交付修正回执后按回执核销关系样本，并把核销所用的报告样本回传。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

ITEM_TABLE = "govern_rectify_items"
RECEIPT_TABLE = "rectify_receipts"

# 整改项状态：待领取 → 整改中 → 部分核销 → 已核销


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class GovernDashService(BaseModuleService):
    MODULE = "govern_dash"
    ENTITY = "治理指标"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["指标编号", "指标名称", "评估对象", "目标值", "当前值", "趋势方向", "更新频率", "最后刷新"]
    REQUIRED_FIELDS = ["指标编号", "指标名称", "评估对象"]
    STATUS_ORDER = ["草稿", "监控中", "偏离基线", "已达标"]
    ACTION_RULES = {"启动监控": "监控中", "确认达标": "已达标", "标记偏离": "偏离基线"}
    NEGATIVE_ACTIONS = []

    # ===== 跨模块数据流实现 =====
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry, message = super().run_action(entry_id, action)
        if entry is None:
            return entry, message
        # 链路 L22: govern_dash → quality_audit（治理偏离基线时触发质量审计）
        if entry.get("status") == "偏离基线":
            audit_msg = self._push_to_quality_audit(entry)
            message += "；" + audit_msg
        # 链路 L23: govern_dash → schedule_job（监控指标触发定时任务）
        if entry.get("status") == "监控中":
            job_msg = self._push_to_schedule_job(entry)
            message += "；" + job_msg
        return entry, message

    def _push_to_quality_audit(self, entry: dict[str, Any]) -> str:
        rows = store.rows("quality_audit")
        next_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        qa_entry: dict[str, Any] = {
            "id": next_id,
            "status": "待审计",
            "pending": True,
            "abnormal": False,
            "报告编号": f"QUAL-GOV-{next_id:04d}",
            "审计范围": f"指标{entry.get('指标名称','')}偏离基线",
            "实体准确率": "re-verify",
            "关系完整率": "re-verify",
            "冗余度": "unknown",
            "更新时效": "立即",
            "合规结论": "待审计",
            "审计时间": str(entry.get("最后刷新", "2026-11-18")),
        }
        rows.append(qa_entry)
        return f"偏离基线已触发质量审计 {qa_entry['报告编号']}"

    def _push_to_schedule_job(self, entry: dict[str, Any]) -> str:
        rows = store.rows("schedule_job")
        next_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        sj_entry: dict[str, Any] = {
            "id": next_id,
            "status": "待激活",
            "pending": True,
            "abnormal": False,
            "作业编号": f"SCHE-GOV-{next_id:04d}",
            "任务类型": f"监控刷新-{entry.get('指标名称','')}",
            "关联图谱": str(entry.get("评估对象", "")),
            "Cron表达式": "0 */6 * * *",
            "时区设置": "Asia/Shanghai",
            "依赖检查": "none",
            "失败通知": "slack",
            "下次执行": "2026-11-19 00:00:00",
        }
        rows.append(sj_entry)
        return f"已创建定时监控任务 {sj_entry['作业编号']}"

    # ===== 治理待办：整改项生成与领取 =====

    def sync_rectify_items(self, batch: dict[str, Any]) -> list[dict[str, Any]]:
        """用整改批次证据生成可分批领取的整改项。

        按批次内的关系错误类型分组，一组生成一个整改项：同一关系的断链、
        误连等冲突判断各自成项，处理人可依证据分批领取、分别核销。
        """
        rows = store.rows(ITEM_TABLE)
        groups: dict[str, list[dict[str, Any]]] = {}
        for ref in batch.get("样本列表", []):
            groups.setdefault(str(ref.get("错误类型")), []).append(ref)
        items: list[dict[str, Any]] = []
        for error_type in sorted(groups):
            refs = groups[error_type]
            item_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
            item: dict[str, Any] = {
                "id": item_id,
                "项编号": f"RECT-{item_id:04d}",
                "批次编号": batch.get("批次编号"),
                "边号": batch.get("边号"),
                "关系描述": batch.get("关系描述", ""),
                "错误类型": error_type,
                "涉及报告": sorted({str(ref.get("报告编号")) for ref in refs}),
                "样本列表": [dict(ref) for ref in refs],
                "状态": "待领取",
                "处理人": "",
                "领取时间": "",
                "核销回执": [],
                "来源模块": "quality_audit",
                "创建时间": _now(),
                "pending": True,
                "abnormal": False,
            }
            rows.append(item)
            items.append(item)
        return items

    def list_rectify_items(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        rows = list(store.rows(ITEM_TABLE))
        for field, expected in (filters or {}).items():
            if expected:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        return rows

    def get_rectify_item(self, item_code: str) -> dict[str, Any] | None:
        for row in store.rows(ITEM_TABLE):
            if row.get("项编号") == item_code:
                return row
        return None

    def claim_rectify_item(
        self, item_code: str, handler: str
    ) -> tuple[dict[str, Any] | None, str]:
        """领取整改项；已被领取或已核销的项不能重复领取。"""
        with store.lock:
            item = self.get_rectify_item(item_code)
            if item is None:
                return None, f"整改项 {item_code} 不存在"
            status = item.get("状态")
            if status == "待领取":
                item["状态"] = "整改中"
                item["处理人"] = handler
                item["领取时间"] = _now()
                return item, f"整改项 {item_code} 已由 {handler or '处理人'} 领取"
            if status == "整改中":
                return None, f"整改项 {item_code} 已被 {item.get('处理人') or '他人'} 领取，不能重复领取"
            return None, f"整改项 {item_code} 当前为「{status}」，不能领取"

    # ===== 修正回执：幂等核销 =====

    def deliver_receipt(
        self,
        *,
        receipt_code: str,
        edge: str,
        error_types: list[str],
        generation: str | None,
        handler: str,
        note: str | None,
    ) -> tuple[dict[str, Any] | None, str]:
        """交付修正回执并核销关系样本。

        回执编号是幂等键：并发或重复交付同一回执只核销一次，后续交付
        返回首次核销的记录，不产生新的核销。核销只落在回执实际处理的
        关系错误类型（及指定图代）上，同边号的其他判断不受影响。
        """
        receipt_code = receipt_code.strip()
        edge = edge.strip()
        types = [t.strip() for t in error_types if t and t.strip()]
        generation = (generation or "").strip() or None
        if not receipt_code or not edge or not types:
            return None, "回执编号、边号、实际处理错误类型均为必填"
        with store.lock:
            receipts = store.rows(RECEIPT_TABLE)
            for record in receipts:
                if record.get("回执编号") == receipt_code:
                    result = dict(record)
                    result["重复回执"] = True
                    result["本次核销样本"] = []
                    return result, (
                        f"回执 {receipt_code} 已受理过，同一回执只核销一次，"
                        f"本次不再重复核销（首次已核销 {len(record.get('核销样本', []))} 个样本）"
                    )
            matched = self._match_pending_samples(edge, types, generation)
            if not matched:
                return None, (
                    f"回执 {receipt_code} 未匹配到待核销的 {edge} 关系样本："
                    "请核对边号/错误类型/图代，或样本已被其他回执核销"
                )
            receipt: dict[str, Any] = {
                "id": max((int(r.get("id", 0)) for r in receipts), default=0) + 1,
                "回执编号": receipt_code,
                "边号": edge,
                "错误类型": types,
                "图代": generation or "",
                "处理人": handler,
                "说明": note or "",
                "核销时间": _now(),
                "核销样本": [],
                "涉及整改项": [],
            }
            # 写回样本与批次（分清实际处理过的关系错误类型）。
            from app.services import service_for

            quality = service_for("quality_audit")
            written_refs: list[dict[str, Any]] = []
            touched_items: dict[str, dict[str, Any]] = {}
            for sample in matched:
                written_refs.append({
                    "样本编号": sample.get("样本编号"),
                    "报告编号": sample.get("报告编号"),
                    "边号": sample.get("边号"),
                    "错误类型": sample.get("错误类型"),
                    "图代": sample.get("图代"),
                    "抽样口径": sample.get("抽样口径"),
                    "批次编号": sample.get("批次编号"),
                })
                item = self._item_of_sample(str(sample.get("样本编号")))
                if item is not None:
                    touched_items[str(item.get("项编号"))] = item
            receipt["核销样本"] = written_refs
            receipt["涉及整改项"] = sorted(touched_items)
            if quality is not None:
                quality.writeoff_samples(matched, receipt)
            for item in touched_items.values():
                self._refresh_item_after_writeoff(item, receipt)
            receipts.append(receipt)
            result = dict(receipt)
            result["重复回执"] = False
            result["本次核销样本"] = list(written_refs)
            return result, f"回执 {receipt_code} 已核销 {len(written_refs)} 个关系样本"

    def _match_pending_samples(
        self, edge: str, types: list[str], generation: str | None
    ) -> list[dict[str, Any]]:
        """在已派工的整改项里找可核销样本：边号+错误类型匹配，图代可选限定。

        只扫描治理待办整改项引用的样本，未入批次的同边号样本
        （例如未受影响图代）天然不会被划入核销。
        """
        from app.services import service_for

        quality = service_for("quality_audit")
        matched: list[dict[str, Any]] = []
        if quality is None:
            return matched
        for item in store.rows(ITEM_TABLE):
            if str(item.get("边号")) != edge:
                continue
            if str(item.get("错误类型")) not in types:
                continue
            for ref in item.get("样本列表", []):
                sample = quality.find_sample(str(ref.get("样本编号")))
                if sample is None or sample.get("状态") != "已归并":
                    continue
                if str(sample.get("错误类型")) not in types:
                    continue
                if generation and str(sample.get("图代")) != generation:
                    continue
                matched.append(sample)
        return matched

    def _item_of_sample(self, sample_code: str) -> dict[str, Any] | None:
        for item in store.rows(ITEM_TABLE):
            for ref in item.get("样本列表", []):
                if ref.get("样本编号") == sample_code:
                    return item
        return None

    def _refresh_item_after_writeoff(
        self, item: dict[str, Any], receipt: dict[str, Any]
    ) -> None:
        """按项内样本核销进度刷新整改项状态，并登记所用回执。"""
        from app.services import service_for

        quality = service_for("quality_audit")
        if quality is None:
            return
        refs = item.get("样本列表", [])
        done = 0
        for ref in refs:
            sample = quality.find_sample(str(ref.get("样本编号")))
            if sample is not None and sample.get("状态") == "已核销":
                done += 1
        if refs and done >= len(refs):
            item["状态"] = "已核销"
            item["pending"] = False
        elif done:
            item["状态"] = "部分核销"
        receipt_code = str(receipt.get("回执编号"))
        if receipt_code not in item.setdefault("核销回执", []):
            item["核销回执"].append(receipt_code)
        if not item.get("处理人") and receipt.get("处理人"):
            item["处理人"] = receipt["处理人"]

    def list_receipts(self) -> list[dict[str, Any]]:
        return list(store.rows(RECEIPT_TABLE))

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        items = store.rows(ITEM_TABLE)
        base["rectify_items"] = {
            "total": len(items),
            "by_status": {
                status: sum(1 for row in items if row.get("状态") == status)
                for status in ("待领取", "整改中", "部分核销", "已核销")
            },
        }
        base["rectify_receipts"] = len(store.rows(RECEIPT_TABLE))
        base["cross_module_consumers"] = ["quality_audit", "schedule_job"]
        return base
