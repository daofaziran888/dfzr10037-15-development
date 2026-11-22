"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import threading
from typing import Any

from app.seed import AUDIT_SAMPLE_SEED, SEED_ROWS

# 跨报告整改链路的辅助表：不作为独立业务模块出现在概览和模块清单里。
AUX_TABLES = (
    "quality_audit_samples",   # 质量审计关系样本（跨报告归并的最小单元）
    "quality_audit_batches",   # 整改批次证据
    "govern_rectify_items",    # 治理待办整改项（依证据分批领取）
    "rectify_receipts",        # 修正回执核销记录（幂等键：回执编号）
)


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._tables["quality_audit_samples"] = [dict(row) for row in AUDIT_SAMPLE_SEED]
        for name in AUX_TABLES:
            self._tables.setdefault(name, [])
        # 回执核销的互斥锁：并发交付同一回执时保证只核销一次。
        self.lock = threading.RLock()

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in AUX_TABLES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
