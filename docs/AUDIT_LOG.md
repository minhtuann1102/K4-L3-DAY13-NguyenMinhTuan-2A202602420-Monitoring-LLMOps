# Dedicated Audit Logging Specification

Hệ thống Audit Log (nhật ký kiểm toán bảo mật) độc lập với application log thông thường (`data/logs.jsonl`), nhằm ghi nhận toàn bộ các thao tác quản trị rủi ro cao và thay đổi cấu hình runtime của hệ thống LLMOps.

## 1. Mục đích và Phân tách trách nhiệm (Separation of Concerns)

- **Application Logs (`data/logs.jsonl`):** Phục vụ gỡ lỗi kỹ thuật, đo lường hiệu năng (`latency_ms`, `tokens_in`, `tokens_out`, `cost_usd`).
- **Audit Logs (`data/audit.jsonl`):** Phục vụ kiểm toán an ninh thông tin, compliance (SOC2, ISO 27001), phát hiện can thiệp cấu hình trái phép, điều tra gian lận hoặc sự cố con người.

## 2. Schema chuẩn

Mỗi bản ghi kiểm toán là một JSON object độc lập chứa các trường bắt buộc:

| Trường | Kiểu | Mô tả | Ví dụ |
|---|---|---|---|
| `audit_id` | String | Định danh duy nhất theo chuẩn `aud-<12-hex>` | `aud-e4b7c19a82f3` |
| `ts` | String | Thời gian thực thi chuẩn ISO-8601 UTC | `2026-09-30T05:08:49.508600Z` |
| `actor` | String | Đối tượng kích hoạt hành động (`admin`, `engineer`, `system`) | `admin` |
| `action` | String | Loại hành vi quản trị nhạy cảm | `INCIDENT_ENABLE`, `INCIDENT_DISABLE`, `PROMPT_PROMOTE`, `PROMPT_ROLLBACK` |
| `resource` | String | Tài nguyên chịu tác động | `incident/rag_slow`, `prompt/day13-chat/v2` |
| `status` | String | Kết quả thực thi (`SUCCESS`, `FAILURE`) | `SUCCESS` |
| `ip_address` | String | Địa chỉ IP của client gửi yêu cầu | `127.0.0.1` |
| `details` | Object | Dữ liệu ngữ cảnh bổ sung (phiên bản cũ/mới, correlation ID) | `{"incident_name": "rag_slow"}` |

### Ví dụ bản ghi thực tế:
```json
{
  "audit_id": "aud-1a2b3c4d5e6f",
  "ts": "2026-09-30T05:08:49.508600Z",
  "actor": "admin",
  "action": "INCIDENT_ENABLE",
  "resource": "incident/rag_slow",
  "status": "SUCCESS",
  "ip_address": "127.0.0.1",
  "details": {
    "incident_name": "rag_slow",
    "correlation_id": "req-a1ba6ee1"
  }
}
```

## 3. Chính sách lưu trữ và Bảo mật (Retention Policy)

- **Nguyên tắc bất biến (Immutability):** File `data/audit.jsonl` hoạt động theo cơ chế append-only. Nghiêm cấm mọi thao tác ghi đè hoặc chỉnh sửa log đã tạo.
- **Thời gian lưu trữ (Retention Lifecycle):**
  - **Hot Storage (90 ngày):** Lưu trữ trên đĩa cục bộ / cloud bucket có tốc độ đọc cao để phục vụ điều tra trực tiếp khi có sự cố.
  - **Cold Storage (365 ngày):** Sau 90 ngày, log được nén gzip và chuyển sang archive storage có mã hóa AES-256 để đáp ứng kiểm toán compliance hàng năm.
- **Phân quyền truy cập:** Chỉ tài khoản có vai trò Security Auditor / SecOps mới có quyền đọc `data/audit.jsonl`. Ứng dụng chỉ có quyền ghi nối (append-only permission).

## 4. Hướng dẫn truy vấn kiểm toán

Dùng script tiện ích `scripts/query_audit.py` để tra cứu nhanh:

```powershell
# Xem toàn bộ sự kiện kiểm toán gần nhất
python scripts/query_audit.py

# Lọc theo hành động (ví dụ thay đổi prompt hoặc incident)
python scripts/query_audit.py --action INCIDENT_ENABLE
python scripts/query_audit.py --action PROMPT_ROLLBACK

# Lọc theo người thực hiện
python scripts/query_audit.py --actor admin
```
