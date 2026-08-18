"""L3 状态守卫基础机制（责任链第三环）。

状态守卫表：动作 × 允许状态，显式校验（非前端隐藏）。冲突抛 `InvalidStateError`。
报销状态机见 docs/api.md §2：draft → pending → approved / returned / manual_review。
"""

from app.core.exceptions import InvalidStateError

# 报销单动作 → 允许状态集合（冻结口径）
REIMBURSEMENT_ACTION_STATES: dict[str, set[str]] = {
    "edit": {"draft", "returned"},
    "upload_attachment": {"draft", "returned"},
    "delete_attachment": {"draft", "returned"},
    "submit": {"draft", "returned"},
    "manual_review": {"manual_review"},
    "return": {"pending"},
}


def ensure_state(current: str, allowed: set[str], action: str = "") -> None:
    """校验当前状态是否允许指定动作，否则抛 409。"""
    if current not in allowed:
        suffix = f"（动作 {action}）" if action else ""
        raise InvalidStateError(f"当前状态 {current} 不允许{suffix}")
