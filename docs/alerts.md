# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: HighLatencyP95
- Severity: warning
- Duration: 5m
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 <= 3000ms
- Điều kiện và thời gian duy trì: p95(latency_ms) > 3000ms trong 5 phút
- Ảnh hưởng tới người dùng: Người dùng phải đợi lâu để nhận được câu trả lời, trải nghiệm kém.
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xem khoảng thời gian bắt đầu tăng.
  2. Lọc file log `data/logs.jsonl` tìm request có latency cao và lấy `correlation_id`.
  3. Mở Langfuse trace với `correlation_id` đó để xem bước nào (retrieval hay LLM generation) tốn thời gian nhất.
- Mitigation tạm thời: Rollback prompt nếu mới cập nhật, hoặc khởi động lại hệ thống RAG nếu lỗi do timeout.
- Owner: student-2A202602420

## Alert 2

- Tên: HighErrorRate
- Severity: critical
- Duration: 5m
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: Error rate <= 2%
- Điều kiện và thời gian duy trì: error_rate_pct > 2% trong 5 phút
- Ảnh hưởng tới người dùng: Người dùng liên tục nhận thông báo lỗi, không thể sử dụng tính năng.
- Ba bước kiểm tra đầu tiên:
  1. Xem dashboard để biết số lượng lỗi và loại lỗi (LLM API lỗi hay Retrieval lỗi).
  2. Tìm trong log các request_failed để xem chi tiết error_type.
  3. Xem trace để biết chính xác module nào ném exception.
- Mitigation tạm thời: Chuyển sang LLM dự phòng, hoặc rollback code mới.
- Owner: student-2A202602420

## Alert 3

- Tên: LowQualityScore
- Severity: warning
- Duration: 10m
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: Quality score >= 0.75
- Điều kiện và thời gian duy trì: quality_score < 0.75 trong 10 phút
- Ảnh hưởng tới người dùng: Trả lời sai, thiếu thông tin, hoặc phản hồi vô nghĩa.
- Ba bước kiểm tra đầu tiên:
  1. Xem panel quality và retrieval success trên dashboard.
  2. So sánh trace của các câu trả lời bị chấm điểm thấp để kiểm tra prompt và context đầu vào.
  3. Kiểm tra xem có phiên bản prompt mới nào vừa được promote hay không.
- Mitigation tạm thời: Rollback prompt version, hoặc sửa lại system prompt.
- Owner: student-2A202602420
