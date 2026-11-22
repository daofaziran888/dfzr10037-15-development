"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import rectify, resource

# rectify 的具体路径（/api/quality_audit/samples 等）必须先于
# 通用资源路由 /api/{module}/{entry_id} 注册，否则会被动态路径抢先匹配。
ROUTERS = [rectify, resource]
