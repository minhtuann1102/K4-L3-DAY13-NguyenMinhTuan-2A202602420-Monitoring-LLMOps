from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", "data/audit.jsonl"))


def record_audit_event(
    *,
    actor: str,
    action: str,
    resource: str,
    status: str = "SUCCESS",
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Ghi log kiểm toán (Audit Log) có cấu trúc bảo mật cao.

    Schema:
      - audit_id: Định danh duy nhất theo định dạng aud-<12-char-hex>
      - ts: Timestamp chuẩn ISO-8601 UTC
      - actor: Người hoặc tiến trình thực hiện hành động (admin, engineer, system)
      - action: Hành động quản trị nhạy cảm (INCIDENT_ENABLE, INCIDENT_DISABLE, PROMPT_PROMOTE, PROMPT_ROLLBACK)
      - resource: Đối tượng tài nguyên bị tác động
      - status: SUCCESS | FAILURE
      - ip_address: IP nguồn gửi yêu cầu
      - details: Dữ liệu bối cảnh bổ sung
    """
    event = {
        "audit_id": f"aud-{uuid.uuid4().hex[:12]}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "resource": resource,
        "status": status,
        "ip_address": ip_address or "127.0.0.1",
        "details": details or {},
    }

    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event
