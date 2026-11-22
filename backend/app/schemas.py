"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


# ===== 跨报告整改链路契约 =====

class MergeSamplesPayload(BaseModel):
    """审计员多选关系样本，归并成整改批次证据。"""

    样本编号: list[str] = Field(default_factory=list)
    处理人: str = ""


class DispatchPayload(BaseModel):
    """整改批次整组派工。"""

    处理人: str = ""


class ClaimPayload(BaseModel):
    """治理待办整改项领取。"""

    处理人: str = ""


class ReceiptPayload(BaseModel):
    """修正回执：回执编号是幂等键，并发/重复交付只核销一次。

    错误类型记录实际处理过哪种关系错误（断链/误连，可多项）；
    图代用于先锁定断链所在版本，只核销该图代内的样本。
    """

    回执编号: str
    边号: str
    错误类型: str | list[str]
    图代: str | None = None
    处理人: str = ""
    说明: str | None = None
