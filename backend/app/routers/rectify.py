"""跨报告整改路由：关系样本归并、批次派工、治理领取与修正回执核销。

路由层只做参数收发，状态流转全部在 app/services 里完成。
具体路径要先于通用资源路由 /api/{module}/{entry_id} 注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.schemas import (
    ClaimPayload,
    DispatchPayload,
    MergeSamplesPayload,
    ReceiptPayload,
)
from app.services import service_for
from app.services.govern_dash import GovernDashService
from app.services.quality_audit import QualityAuditService

router = APIRouter(prefix="/api", tags=["跨报告整改"])


def _quality() -> QualityAuditService:
    service = service_for("quality_audit")
    assert isinstance(service, QualityAuditService)
    return service


def _govern() -> GovernDashService:
    service = service_for("govern_dash")
    assert isinstance(service, GovernDashService)
    return service


# ===== 质量审计：关系样本与整改批次证据 =====

@router.get("/quality_audit/samples")
def list_samples(
    报告编号: str | None = Query(default=None),
    边号: str | None = Query(default=None),
    错误类型: str | None = Query(default=None),
    状态: str | None = Query(default=None),
) -> dict[str, Any]:
    """关系样本池：审计员多选来自多份质量报告的样本。"""
    filters = {
        key: value.strip()
        for key, value in {
            "报告编号": 报告编号, "边号": 边号, "错误类型": 错误类型, "状态": 状态,
        }.items()
        if value and value.strip()
    }
    items = _quality().list_samples(filters)
    return {"items": items, "total": len(items)}


@router.post("/quality_audit/batches/merge")
def merge_samples(payload: MergeSamplesPayload) -> dict[str, Any]:
    """把多选的关系样本批量归并成整改批次证据。"""
    batch, message = _quality().merge_samples(payload.样本编号, payload.处理人)
    return {"ok": batch is not None, "message": message, "batch": batch}


@router.get("/quality_audit/batches")
def list_batches() -> dict[str, Any]:
    items = _quality().list_batches()
    return {"items": items, "total": len(items)}


@router.get("/quality_audit/batches/{batch_code}")
def get_batch(batch_code: str) -> dict[str, Any]:
    """批次详情：含每个样本的原报告与抽样依据，整组派工后仍可回看。"""
    batch = _quality().get_batch(batch_code)
    if batch is None:
        return {"ok": False, "message": f"整改批次 {batch_code} 不存在", "batch": None}
    return {"ok": True, "message": "ok", "batch": batch}


@router.post("/quality_audit/batches/{batch_code}/dispatch")
def dispatch_batch(batch_code: str, payload: DispatchPayload) -> dict[str, Any]:
    """整组派工：同步治理待办，生成可依证据分批领取的整改项。"""
    batch, message, items = _quality().dispatch_batch(batch_code, payload.处理人)
    return {"ok": batch is not None, "message": message, "batch": batch, "items": items}


# ===== 治理待办：整改项领取与修正回执 =====

@router.get("/govern_dash/rectify-items")
def list_rectify_items(
    批次编号: str | None = Query(default=None),
    边号: str | None = Query(default=None),
    状态: str | None = Query(default=None),
) -> dict[str, Any]:
    filters = {
        key: value.strip()
        for key, value in {"批次编号": 批次编号, "边号": 边号, "状态": 状态}.items()
        if value and value.strip()
    }
    items = _govern().list_rectify_items(filters)
    return {"items": items, "total": len(items)}


@router.post("/govern_dash/rectify-items/{item_code}/claim")
def claim_rectify_item(item_code: str, payload: ClaimPayload) -> dict[str, Any]:
    item, message = _govern().claim_rectify_item(item_code, payload.处理人)
    return {"ok": item is not None, "message": message, "item": item}


@router.get("/govern_dash/rectify-receipts")
def list_receipts() -> dict[str, Any]:
    items = _govern().list_receipts()
    return {"items": items, "total": len(items)}


@router.post("/govern_dash/rectify-receipts")
def deliver_receipt(payload: ReceiptPayload) -> dict[str, Any]:
    """交付修正回执：幂等核销，并回传实际核销所用的报告样本。"""
    types = payload.错误类型 if isinstance(payload.错误类型, list) else [payload.错误类型]
    receipt, message = _govern().deliver_receipt(
        receipt_code=payload.回执编号,
        edge=payload.边号,
        error_types=types,
        generation=payload.图代,
        handler=payload.处理人,
        note=payload.说明,
    )
    remaining = [
        {
            "项编号": item.get("项编号"),
            "边号": item.get("边号"),
            "错误类型": item.get("错误类型"),
            "状态": item.get("状态"),
        }
        for item in _govern().list_rectify_items({"边号": payload.边号})
        if item.get("状态") in ("待领取", "整改中", "部分核销")
    ]
    return {
        "ok": receipt is not None,
        "message": message,
        "receipt": receipt,
        "剩余待整改": remaining,
    }
