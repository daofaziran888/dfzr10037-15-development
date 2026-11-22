"""质量审计领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。

跨报告合并重复发现：审计员多选多份报告的关系样本，归并成整改批次证据，
整组派工后同步治理待办；回执核销后由本服务把结果写回样本与批次。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

SAMPLE_TABLE = "quality_audit_samples"
BATCH_TABLE = "quality_audit_batches"

# 关系样本状态：待归并 → 已归并 → 已核销
# 批次状态：待派工 → 已派工 → 部分核销 → 已核销


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class QualityAuditService(BaseModuleService):
    MODULE = "quality_audit"
    ENTITY = "审计报告"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["报告编号", "审计范围", "实体准确率", "关系完整率", "冗余度", "更新时效", "合规结论", "审计时间"]
    REQUIRED_FIELDS = ["报告编号", "审计范围", "实体准确率"]
    STATUS_ORDER = ["待审计", "审计中", "已通过", "需整改"]
    ACTION_RULES = {"发起审计": "审计中", "确认通过": "已通过", "指派整改": "需整改"}
    NEGATIVE_ACTIONS = []

    # ===== 跨报告关系样本归并 =====

    def list_samples(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """关系样本池：审计员从这里多选来自多份报告的样本。"""
        rows = list(store.rows(SAMPLE_TABLE))
        for field, expected in (filters or {}).items():
            if expected:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        return rows

    def find_sample(self, sample_code: str) -> dict[str, Any] | None:
        for row in store.rows(SAMPLE_TABLE):
            if row.get("样本编号") == sample_code:
                return row
        return None

    @staticmethod
    def sample_ref(sample: dict[str, Any]) -> dict[str, Any]:
        """样本溯源快照：整组派工后仍可回看各自原报告和抽样依据。"""
        return {
            "样本编号": sample.get("样本编号"),
            "报告编号": sample.get("报告编号"),
            "边号": sample.get("边号"),
            "错误类型": sample.get("错误类型"),
            "图代": sample.get("图代"),
            "抽样口径": sample.get("抽样口径"),
        }

    def merge_samples(
        self, sample_codes: list[str], handler: str
    ) -> tuple[dict[str, Any] | None, str]:
        """把多选的关系样本归并成一份整改批次证据。

        只归并显式选中的样本：边号相同但未被选中的样本（例如未受影响图代）
        不会被划入整改；同一关系的冲突判断（断链/误连）允许共存于同一批次。
        """
        codes = [code.strip() for code in sample_codes if code and code.strip()]
        if not codes:
            return None, "请先多选要归并的关系样本"
        picked: list[dict[str, Any]] = []
        for code in dict.fromkeys(codes):
            sample = self.find_sample(code)
            if sample is None:
                return None, f"关系样本 {code} 不存在"
            if sample.get("状态") != "待归并":
                return None, f"关系样本 {code} 已入批次 {sample.get('批次编号') or '—'}，不能重复归并"
            picked.append(sample)
        edges = {str(sample.get("边号")) for sample in picked}
        if len(edges) != 1:
            return None, "一份整改批次证据只针对同一条关系边，请按边号分批归并"
        reports = sorted({str(sample.get("报告编号")) for sample in picked})
        if len(reports) < 2:
            return None, "整改批次证据需合并来自至少两份质量报告的样本"
        rows = store.rows(BATCH_TABLE)
        batch_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        batch_code = f"BATCH-{batch_id:04d}"
        error_types = sorted({str(sample.get("错误类型")) for sample in picked})
        batch: dict[str, Any] = {
            "id": batch_id,
            "批次编号": batch_code,
            "边号": picked[0].get("边号"),
            "关系描述": picked[0].get("关系描述", ""),
            "错误类型": error_types,
            "冲突标记": len(error_types) > 1,
            "涉及报告": reports,
            "样本列表": [self.sample_ref(sample) for sample in picked],
            "状态": "待派工",
            "处理人": handler,
            "归并时间": _now(),
            "派工时间": "",
            "pending": True,
            "abnormal": False,
        }
        rows.append(batch)
        for sample in picked:
            sample["状态"] = "已归并"
            sample["批次编号"] = batch_code
        return batch, f"已把 {len(picked)} 个关系样本归并成整改批次证据 {batch_code}"

    # ===== 整改批次证据 =====

    def list_batches(self) -> list[dict[str, Any]]:
        return list(store.rows(BATCH_TABLE))

    def get_batch(self, batch_code: str) -> dict[str, Any] | None:
        for row in store.rows(BATCH_TABLE):
            if row.get("批次编号") == batch_code:
                return row
        return None

    def dispatch_batch(
        self, batch_code: str, handler: str
    ) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        """整组派工：批次状态流转，并把审计结果同步到治理待办生成整改项。"""
        batch = self.get_batch(batch_code)
        if batch is None:
            return None, f"整改批次 {batch_code} 不存在", []
        if batch.get("状态") != "待派工":
            return None, f"整改批次 {batch_code} 当前为「{batch.get('状态')}」，不能重复派工", []
        batch["状态"] = "已派工"
        batch["派工时间"] = _now()
        if handler:
            batch["处理人"] = handler
        # 延迟导入，避免服务注册表循环依赖。
        from app.services import service_for

        govern = service_for("govern_dash")
        items = govern.sync_rectify_items(batch) if govern is not None else []
        message = f"整改批次 {batch_code} 已整组派工，同步治理待办生成 {len(items)} 个整改项"
        return batch, message, items

    # ===== 回执核销写回 =====

    def writeoff_samples(
        self, samples: list[dict[str, Any]], receipt: dict[str, Any]
    ) -> None:
        """把回执核销结果写回关系样本与整改批次（由治理侧在锁内调用）。

        样本记录核销所用回执，批次按样本核销进度流转为部分核销/已核销。
        """
        receipt_code = str(receipt.get("回执编号"))
        stamp = str(receipt.get("核销时间"))
        touched_batches: set[str] = set()
        for sample in samples:
            sample["状态"] = "已核销"
            sample["核销回执"] = receipt_code
            sample["核销时间"] = stamp
            sample["pending"] = False
            if sample.get("批次编号"):
                touched_batches.add(str(sample["批次编号"]))
        for batch_code in touched_batches:
            batch = self.get_batch(batch_code)
            if batch is None:
                continue
            refs = [self.find_sample(ref["样本编号"]) for ref in batch.get("样本列表", [])]
            total = len(batch.get("样本列表", []))
            done = sum(1 for ref in refs if ref is not None and ref.get("状态") == "已核销")
            if total and done >= total:
                batch["状态"] = "已核销"
                batch["pending"] = False
            elif done:
                batch["状态"] = "部分核销"

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        samples = store.rows(SAMPLE_TABLE)
        batches = store.rows(BATCH_TABLE)
        base["relation_samples"] = {
            "total": len(samples),
            "待归并": sum(1 for row in samples if row.get("状态") == "待归并"),
            "已归并": sum(1 for row in samples if row.get("状态") == "已归并"),
            "已核销": sum(1 for row in samples if row.get("状态") == "已核销"),
        }
        base["rectify_batches"] = {
            "total": len(batches),
            "by_status": {
                status: sum(1 for row in batches if row.get("状态") == status)
                for status in ("待派工", "已派工", "部分核销", "已核销")
            },
        }
        base["cross_module_consumers"] = ["govern_dash"]
        return base
