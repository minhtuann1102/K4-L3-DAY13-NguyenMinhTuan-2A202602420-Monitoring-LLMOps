# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Chỉ cần 3 output text và 5 ảnh runtime; dùng đường dẫn tương đối, ví dụ `evidence/03-incident-trace.png`.

## 1. Thông tin học viên

- **Họ và tên:** Nguyễn Minh Tuấn
- **MSSV:** 2A202602420
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/minhtuann1102/K4-L3-DAY13-NguyenMinhTuan-2A202602420-Monitoring-LLMOps
- **Commit SHA cuối:** `4a8a21c`
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602420`

## 2. Evidence index

| Evidence | Đường dẫn | Trạng thái |
|---|---|---|
| Pytest cuối | `evidence/01-pytest.png` | có (22 passed) |
| Log validator | `evidence/02-log-validator.png` | có |
| Dashboard validator | `evidence/03-dashboard-validator.png` | có |
| Structured log | `evidence/04-structured-log-1.png`, `evidence/04-structured-log-2.png` | có |
| PII redaction | `evidence/05-pii-redaction-1.png`, `evidence/05-pii-redaction-2.png` | có |
| Trace list | `evidence/06-trace-list.png` | có |
| Trace waterfall | `evidence/07-trace-waterfall.png` | có |
| Trace metadata | `evidence/08a-trace-metadata.png`, `evidence/08b-trace-metadata.png` | có |
| Prompt versions | `evidence/09-prompt-versions.png` | có |
| Prompt rollback | `evidence/10-prompt-rollback.png` | có |
| Dashboard runtime | `evidence/11-dashboard-overview.png` | có |
| Incident metric | `evidence/12-incident-metric.png` | có |
| Incident log | `evidence/13-incident-log.png` | có |
| Incident trace | `evidence/14-incident-trace.png` | có |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | Baseline thiếu `correlation_id` (giá trị `MISSING`), thiếu enrichment nên fail 3/4 hạng mục. Sau khi hoàn thiện middleware + bind context + PII processor: 4/4 hạng mục PASS, 0 PII leak |
| `validate_dashboard.py` | 6/6 | 6/6 | Contract `config/dashboard.yaml` không phải sửa, nhưng baseline chưa có dashboard runtime |
| `pytest` | 22 passed | 22 passed | Baseline đã xanh; trong lúc làm có 1 test đỏ do thêm key vào metadata span (xem mục 8) rồi sửa lại |
| Số traces hợp lệ | 0 | 86 root trace (project `day13-k4-l3b-2A202602420`, cửa sổ 6 giờ) | Đạt yêu cầu ≥10 trace, đủ cây root → retrieval → generation |
| Số PII leak | 0 | 0 | `payload` đi qua `summarize_text()`; processor `scrub_event` chạy trước JSON renderer và file writer |
| Latency P95 / TTFT P95 | ≈151 ms / 50 ms (3 request thử) | 1443 ms / 50 ms (cửa sổ 60 phút, 38–48 request) | P99 3806 ms là request đầu tiên của load test (cold start + fetch prompt lần đầu); TTFT luôn 50 ms |
| Retrieval success rate | 100% | 100% (38/38) | Đo từ `response_sent.tool_success`, hiển thị trong panel Errors |

Baseline được đo lại trên code starter tại `HEAD` (worktree riêng, log sạch) để có số liệu đối chiếu:
`validate_logs.py` = 30/100, `validate_dashboard.py` = 6/6, `pytest` = 22 passed.

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `app/middleware.py` (`CorrelationIdMiddleware`) chạy `clear_contextvars()` để không rò context giữa các request, sau đó nhận `x-request-id` do client gửi hoặc sinh mới theo format `req-<8-hex>` (`f"req-{uuid.uuid4().hex[:8]}"`), bind vào structlog contextvars và lưu vào `request.state.correlation_id`. Response trả lại `x-request-id` và `x-response-time-ms`. `app/main.py` truyền `correlation_id` vào `agent.run()` để gắn cùng ID đó vào metadata trace Langfuse.
- **Các metadata được ghi vào structured log:** bắt buộc `ts`, `level`, `service`, `event`, `correlation_id`; enrichment bind trước dòng `request_received` gồm `user_id_hash` (SHA-256 rút gọn 12 ký tự), `session_id`, `feature`, `model`, `env`. Riêng `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`; `request_failed` có `error_type`.
- **Cách bảo đảm PII được scrub trước khi ghi:** `app/pii.py` định nghĩa 4 pattern (`email`, `phone_vn`, `cccd`, `credit_card`) và hàm `scrub_text()`. `scrub_event` được đăng ký trong `structlog` processors **trước** `JsonlFileProcessor` và `JSONRenderer`, nên dữ liệu đã được thay bằng `[REDACTED_*]` trước khi serialize/ghi file. `payload.message_preview`/`answer_preview` luôn đi qua `summarize_text()` → `scrub_text()`.
- **Cách kiểm chứng kết quả:** `python scripts/validate_logs.py` → `Estimated Score: 100/100`, `Potential PII leaks detected: 0` trên 105 dòng log; test PII nhập email/điện thoại VN/CCCD/thẻ và kiểm tra output log có `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CCCD]`, `[REDACTED_CREDIT_CARD]` (evidence `04-structured-log-1.png`, `05-pii-redaction-1.png`, `05-pii-redaction-2.png`).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** key Langfuse trong `.env` chỉ thuộc project `day13-k4-l3b-2A202602420` (ảnh `06-trace-list.png` thấy rõ tên project khi đang đăng nhập tài khoản cá nhân). Toàn bộ trace sinh ra từ workload tôi tự chạy (`scripts/load_test.py`, `scripts/prompt_versioning.py run`), không dùng trace/ID của người khác. Snapshot 6 giờ gần nhất có 86 root trace.
- **Cấu trúc root/retrieval/generation observations:** trace name `day13-agent-request` → span `lab-agent-run` (type `agent`, gắn bằng `@observe` trên `LabAgent.run`) → hai child observation: `retrieval` (type `span`, `@observe` trên `mock_rag.retrieve`, có `input` đã scrub) và `generation` (type `generation`, `@observe(as_type="generation")` trên `FakeLLM.generate`, gắn `model`, `usage_details={input,output,total}`, `cost_details={total}`). Cây này đọc được trong `07-trace-waterfall.png` và đã kiểm chứng lại bằng API observations cho cả 8 trace bên dưới.
- **Cách nối trace với log:** metadata trace chứa `correlation_id` (đặt qua `propagate_attributes(metadata=...)` trong `LabAgent.run` và `app/main.py`), cùng với `feature`, `model`, `prompt_name`, `prompt_label`, `prompt_version`, `prompt_source`. `scripts/prompt_versioning.py run` in ra bảng `correlation_id → trace_id` để đối chiếu trực tiếp với dòng log trong `data/logs.jsonl`.
- **Prompt name:** `day13-chat` (text prompt, đủ 3 biến `{{feature}}`, `{{docs}}`, `{{message}}`)
- **Version/label baseline:** version **1** — labels `baseline` + `production` (nội dung giống template local `DEFAULT_PROMPT_TEMPLATE`)
- **Version/label candidate:** version **2** — label `candidate` (thêm ràng buộc độ dài câu trả lời và nêu tài liệu dùng để trả lời)
- **Trace ID của mỗi version:** cùng một input `"Explain why metrics traces and logs work together"`:

| Label | Prompt version | Trace ID | correlation_id | tokens (in/out) | cost (USD) | latency |
|---|---|---|---|---|---|---|
| `baseline` | v1 | `1a186b82dc9fdddbefe5fe2c2d2b45b1` | `req-b5bbb726` | 32 / 161 | 0.002511 | 466 ms |
| `baseline` | v1 | `b3489ee5aa62bd81a404cb721ebb7770` | `req-4caa9d1d` | 32 / 139 | 0.002181 | 153 ms |
| `candidate` | v2 | `1581872604cf98d1c0287e834fae5962` | `req-34094401` | 50 / 109 | 0.001785 | 405 ms |
| `candidate` | v2 | `d65ca28f5737e7c10dd12d0ddff956ed` | `req-72fb1cc7` | 50 / 139 | 0.002235 | 152 ms |
| `production` sau promote | v2 | `1f47d706ec9aa973b64a49c1c100cdd0` | `req-48740f33` | 50 / 147 | 0.002355 | 374 ms |
| `production` sau promote | v2 | `16b78c181cb684082b4157014ebba6c6` | `req-ecf71313` | 50 / 105 | 0.001725 | 152 ms |
| `production` sau rollback | v1 | `6cad7c638aeb1210d7b33a709a6ccaee` | `req-0358a83e` | 32 / 145 | 0.002271 | 153 ms |
| `production` sau rollback | v1 | `6657bc3c21a3f3bf28e15d4a5aa20fbd` | `req-3152c5fd` | 32 / 178 | 0.002766 | 152 ms |

  Nhận xét có bằng chứng: v2 dài hơn nên `input_tokens` tăng từ 32 → 50 cho cùng một câu hỏi, trong khi `output_tokens` vẫn nằm trong khoảng 105–178 do fake LLM sinh ngẫu nhiên. Đây là lý do prompt version phải nằm trong trace metadata: khi cost/token tăng bất thường, ta biết ngay request đó đang dùng version nào.
- **Cách promote và rollback `production`:** label do Langfuse giữ, app không hard-code version nên chỉ cần đổi label là xong (không sửa code, không restart API):
  1. Promote: `python scripts/prompt_versioning.py promote --version 2` → `production` chuyển v1 → v2. Chạy lại workload cùng input → trace ghi `day13-chat/production/v2` (2 trace ở bảng trên).
  2. Rollback: `python scripts/prompt_versioning.py rollback --version 1` → `production` quay về v1. Chạy lại workload cùng input → trace ghi `day13-chat/production/v1` (2 trace ở bảng trên).
  3. Trạng thái cuối: `v1 = [baseline, production]`, `v2 = [candidate]` — kiểm tra bằng `python scripts/prompt_versioning.py status`.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** contract là `config/dashboard.yaml` (6 panel: latency, traffic, errors, cost, tokens, quality). Dashboard runtime là `scripts/serve_dashboard.py` — script local không cần thêm package, đọc trực tiếp `data/logs.jsonl`, phục vụ tại `http://127.0.0.1:8501`, tự refresh 30 giây, time range mặc định 60 phút, mỗi panel có tên, câu hỏi vận hành, đơn vị, threshold/SLO line và trạng thái ĐẠT/VƯỢT NGƯỠNG:
  1. `Latency percentiles and TTFT` (ms) — P50/P95/P99 của `response_sent.latency_ms` và TTFT P95, threshold `p95 ≤ 3000`.
  2. `Request traffic` (requests_per_minute) — số `request_received` theo phút, threshold `rate_per_minute ≥ 1`.
  3. `Error rate and retrieval success` (percent) — error rate từ `request_failed/request_received`, breakdown theo `error_type`, retrieval success từ `response_sent.tool_success`, threshold `error_rate ≤ 2`.
  4. `Cost over time` (usd) — tổng `cost_usd` theo phút và cả cửa sổ, threshold `total ≤ 2.5`.
  5. `Input and output tokens` (tokens) — tổng `tokens_in`/`tokens_out`, threshold `sum ≤ 50000`.
  6. `Quality proxy` (score_0_to_1) — mean `quality_score`, threshold `mean ≥ 0.75`.
  Snapshot lúc chụp: P95 = 1443 ms, error rate = 0%, retrieval success = 100%, quality avg = 0.863, cost = $0.101952 — tất cả đều ĐẠT ngưỡng. Evidence: `11-dashboard-overview.png`.
- **SLO và lý do chọn:** `config/slo.yaml` — `fast_successful_requests`, cửa sổ 28 ngày, SLI good event `event == "response_sent" and latency_ms <= 3000`, total event `event == "request_received"`, target **99.5%**. Chọn 3000 ms vì P95 thực đo ≈1400 ms và P99 ≈3800 ms chỉ xuất hiện ở request cold-start, nên 3000 ms là ranh giới "user còn chấp nhận được" đồng thời khớp đúng alert `HighLatencyP95`. Chọn 99.5% vì đây là API nội bộ, không cần 99.9% nhưng vẫn buộc phải xử lý lỗi hệ thống.
- **Cách tính error budget:** SLO 99.5% ⇒ error budget 0.5%. Theo request: 10.000 request trong 28 ngày thì tối đa **50 request** được phép lỗi hoặc chậm hơn 3000 ms. Theo thời gian: 0.5% × 28 ngày ≈ **201,6 phút**. Nếu error rate vượt 2% (guardrail trong `config/slo.yaml`) trong 5 phút thì alert `HighErrorRate` bắn và phải cân nhắc rollback prompt/khôi phục cấu hình để không đốt hết error budget.
- **Ba alert và runbook tương ứng:** khai báo trong `config/alert_rules.yaml`, hướng dẫn xử lý trong `docs/alerts.md`:
  1. `HighLatencyP95` — warning, `p95(latency_ms) > 3000ms` trong `5m`, kênh Slack, owner `student-2A202602420`, runbook `docs/alerts.md#alert-1`. Kiểm tra: panel latency → lọc log lấy `correlation_id` có latency cao → mở trace cùng ID xem span `retrieval` hay `generation` chậm.
  2. `HighErrorRate` — critical, `error_rate_pct > 2` trong `5m`, runbook `docs/alerts.md#alert-2`. Kiểm tra: panel errors theo `error_type` → lọc `request_failed` trong log → xem trace lỗi để biết module ném exception.
  3. `LowQualityScore` — warning, `quality_score < 0.75` trong `10m`, runbook `docs/alerts.md#alert-3`. Kiểm tra: panel quality + retrieval success → so trace của các câu trả lời điểm thấp → kiểm tra prompt version vừa promote.

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (Cohort K4-L3B, seed: `1312`, incident: `rag_slow`, feature: `monitoring`, threshold: `2000ms`)
- **Khoảng thời gian điều tra:** 2026-09-30 12:09:00 — 12:12:00 (UTC 05:09:00 — 05:12:00)
- **Triệu chứng từ metrics:** Panel 1 `Latency percentiles and TTFT` trên dashboard runtime hiển thị trạng thái cảnh báo **`VƯỢT NGƯỠNG`** màu đỏ. Latency P50 tăng vọt lên **2653 ms**, P95 và P99 chạm mốc **3559 ms** (vượt xa ngưỡng SLO nội bộ `p95 <= 3000 ms` và ngưỡng của challenge `2000 ms`). Đồ thị latency có đỉnh nhọn rõ rệt; trong khi đó Error rate vẫn giữ 0%, Retrieval success đạt 100% và Quality score trung bình 0.84. Evidence: `evidence/12-incident-metric.png`.
- **Log line và correlation ID liên quan:** Lọc `data/logs.jsonl` trong khung giờ trên ghi nhận 5 request liên tiếp của feature `monitoring` có latency cao bất thường từ 2652 ms đến 3559 ms. Đại diện là request đầu tiên với `correlation_id="req-40c6b69c"`:
  - Log `request_received`: `ts="2026-09-30T05:09:02.524607Z"`, `service="api"`, `user_id_hash="4a1a454d70a9"`, `session_id="k4-l3b-challenge-s01"`, `feature="monitoring"`, `payload.message_preview="Explain why metrics traces and logs work together."`.
  - Log `response_sent`: `ts="2026-09-30T05:09:06.174327Z"`, `service="api"`, `latency_ms=3559`, `ttft_ms=50`, `tokens_in=35`, `tokens_out=166`, `tool_name="retrieval"`, `tool_success=true`. Evidence: `evidence/13-incident-log.png`.
- **Trace ID và span gây ảnh hưởng:** Mở trace tương ứng trên Langfuse theo `session_id="k4-l3b-challenge-s01"` và `correlation_id="req-40c6b69c"` tìm thấy `trace_id="810c300e56dfe6ac3b468eba03f962e5"`. Cây waterfall phân tích rõ:
  - Root observation `lab-agent-run` (type `agent`): tổng thời gian **3.56s**.
  - Child span `retrieval`: thực thi mất **2.502s** (chiếm tới ~70% tổng latency).
  - Child generation `generation`: chỉ mất **0.157s** (hoàn toàn bình thường).
  - Evidence: `evidence/14-incident-trace.png`.
- **Root cause:** Kích hoạt incident `rag_slow` (`STATE["rag_slow"] = True`) làm hàm `retrieve()` trong `app/mock_rag.py` bị trễ thêm `time.sleep(2.5)`. Độ trễ từ việc truy xuất vector store kéo dài tới 2.50s là nguyên nhân trực tiếp đẩy tổng thời gian xử lý vượt ngưỡng SLO 2000 ms/3000 ms. Thêm vào đó, do hàm `chat` trong `app/main.py` là hàm `async` nhưng gọi logic đồng bộ của agent trực tiếp trên event loop, các request chạy đồng thời bị xếp hàng chờ, khiến tổng thời gian hoàn tất đợt workload 5 request lên tới hơn 14 giây.
- **Fix action:**
  1. Khôi phục dịch vụ tức thời: gọi API `POST /incidents/rag_slow/disable` (hoặc chạy `python scripts/inject_incident.py --disable`) để đưa `STATE["rag_slow"]` về `False`.
  2. Trong hệ thống production: cấu hình timeout và circuit breaker cho vector store / retrieval service (ví dụ timeout 1.5s kèm fallback về local cache hoặc general docs).
  3. Bọc lệnh gọi I/O retrieval/LLM bằng `run_in_threadpool` hoặc chuyển sang async client để giải phóng event loop FastAPI.
- **Preventive measure:**
  1. Duy trì alert rule `HighLatencyP95` (`p95(latency_ms) > 3000ms` trong 5 phút) để nhận diện ngay khi retrieval bị bottleneck.
  2. Bổ sung metric riêng cho từng component: tách biệt `retrieval_latency_ms` và `generation_latency_ms` trên dashboard để cô lập ngay tầng lỗi mà không cần tra cứu thủ công từng trace.
  3. Bổ sung automated health check và degradation policy: nếu retrieval P95 > 2s trong 3 phút thì tự động chuyển sang degraded mode (giảm số document chunks hoặc dùng cache kết quả truy vấn gần nhất).

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** instrument child observation ngay tại nơi phát sinh số liệu bằng `@observe` (`mock_rag.retrieve()` → span `retrieval`, `FakeLLM.generate()` → generation `generation`) thay vì mở observation thủ công trong `LabAgent.run`. Lý do: ít xâm lấn vào logic agent, tự động đúng quan hệ cha–con dưới `lab-agent-run`, và generation nhận `model`/`usage_details`/`cost_details` ngay chỗ có số token/cost thật. Quyết định thứ hai: giữ `correlation_id`, `feature`, `model` ở metadata trace-level qua `propagate_attributes` chứ không nhét thêm vào metadata của span `lab-agent-run`, vì public test `tests/test_agent_prompt_trace.py` so khớp chính xác 7 key của span đó; cách này vẫn thỏa yêu cầu "correlation ID phải xuất hiện trong trace metadata".
- **Một lỗi/blocker đã gặp:** lần chạy CP2 đầu tiên có **10 request trả HTTP 500** (`event=request_failed`, `error_type=TypeError`) trong `data/logs.jsonl`. Chi tiết lỗi: `Langfuse.update_current_generation() got an unexpected keyword argument 'usage'`.
- **Cách tìm nguyên nhân và xử lý:** vì log có `error_type` nên chỉ cần `Group-Object error_type` trên file log là thấy ngay TypeError; đọc `detail` trong payload chỉ ra chính xác tham số sai. Nguyên nhân là đã dùng tên tham số của SDK cũ (`usage=`) trong khi Langfuse Python SDK v4 dùng `usage_details` và `cost_details`. Xử lý: sửa lại `app/mock_llm.py` cho đúng signature của `langfuse 4.15.6`, khởi động lại API và chạy lại load test → 28/28 request sau đó đều 200 và generation có đủ token/cost. Blocker này cũng là ví dụ thực tế cho thấy vì sao lỗi phải được ghi log có cấu trúc kèm `error_type` thay vì chỉ in stack trace.
- **Cách hiểu luồng Metrics → Logs → Traces:** metric cho biết triệu chứng và khoảng thời gian (ví dụ panel latency P95 = 3559 ms báo vượt ngưỡng 3000 ms); log với `correlation_id` chỉ ra đúng request bị ảnh hưởng (`req-40c6b69c`, `latency_ms=3559`); trace cùng `correlation_id` chỉ ra bước gây vấn đề — span `retrieval` mất 2.502s trong khi `generation` chỉ mất 0.157s, kết luận chính xác 100% nguyên nhân nằm ở tầng retrieval RAG.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt là một phần của hệ thống nên phải được version hóa và gắn label. Bằng chứng cụ thể: đổi `production` sang v2 làm `input_tokens` của cùng một câu hỏi tăng 32 → 50 (cost/request tăng theo), nên nếu không ghi `prompt_version`/`prompt_label` vào trace thì khi cost tăng bất thường ta không biết do prompt hay do workload. Khi version mới gây hại, rollback chỉ là đổi label ở Langfuse về v1 — không sửa code, không deploy lại; sau rollback trace lại ghi `production/v1` và token trở về 32. SLO/error budget biến các con số đó thành ngưỡng có thể hành động: P95 ≤ 3000 ms, error rate ≤ 2%, quality ≥ 0.75, cost ≤ 2.5 USD/ngày, và alert chỉ bắn khi metric xấu kéo dài (5–10 phút) để tránh nhiễu.
- **Điều quan trọng nhất đã học:** Khả năng liên kết chặt chẽ ba trụ cột Observability (Metrics → Logs → Traces) thông qua correlation ID giúp rút ngắn thời gian chẩn đoán sự cố (MTTD & MTTR) từ hàng giờ xuống vài chục giây, đồng thời việc version hóa Prompt như code là yếu tố sống còn để kiểm soát chất lượng và chi phí trong các hệ thống LLMOps.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** toàn bộ evidence 01–14 của cả 3 checkpoint đã hoàn thành đầy đủ; dashboard runtime là script local (không phải Grafana) nên chỉ xem được khi chạy `python scripts/serve_dashboard.py`; `data/audit.jsonl` (bonus audit log) và phần cost optimization/CI chưa làm.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Đầy đủ bằng chứng output text và ảnh runtime theo hướng dẫn.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
