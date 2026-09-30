"""Dashboard runtime 6 panel cho CP2, đọc dữ liệu thật từ `data/logs.jsonl`.

Panel, đơn vị và threshold lấy trực tiếp từ `config/dashboard.yaml` (contract),
nên dashboard luôn khớp contract mà không cần cài thêm package ngoài requirements.

Cách dùng:
    python scripts/serve_dashboard.py              # mo http://127.0.0.1:8501, refresh 30s
    python scripts/serve_dashboard.py --once       # chi in snapshot so lieu ra terminal
    python scripts/serve_dashboard.py --window-minutes 120
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio  # noqa: E402

import yaml  # noqa: E402

CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"
LOG_PATH = Path(os.getenv("LOG_PATH", "data/logs.jsonl"))
LOCAL_TZ = datetime.now().astimezone().tzinfo


def load_panel_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)["dashboard"]


def load_events(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    events: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw_ts = record.get("ts")
        if not raw_ts:
            continue
        try:
            record["_ts"] = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        events.append(record)
    return events


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    items = sorted(values)
    index = max(0, min(len(items) - 1, round((p / 100) * len(items) + 0.5) - 1))
    return float(items[index])


def window_events(events: list[dict], minutes: int) -> tuple[list[dict], datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)
    selected = [event for event in events if start <= event["_ts"] <= now]
    return selected, start, now


def minute_keys(start: datetime, end: datetime) -> list[datetime]:
    cursor = start.replace(second=0, microsecond=0)
    keys: list[datetime] = []
    while cursor <= end:
        keys.append(cursor)
        cursor += timedelta(minutes=1)
    return keys


def bucket_label(moment: datetime) -> str:
    return moment.astimezone(LOCAL_TZ).strftime("%H:%M")


def group_by_minute(events: list[dict]) -> dict[datetime, list[dict]]:
    grouped: dict[datetime, list[dict]] = defaultdict(list)
    for event in events:
        key = event["_ts"].replace(second=0, microsecond=0)
        grouped[key].append(event)
    return grouped


def svg_chart(
    points: list[tuple[str, float]],
    threshold: float | None,
    unit: str,
    width: int = 560,
    height: int = 170,
    color: str = "#2563eb",
) -> str:
    if not points:
        return f'<div class="empty">Không có dữ liệu trong cửa sổ thời gian này</div>'
    values = [value for _, value in points]
    top = max(values + ([threshold] if threshold is not None else []))
    top = top if top > 0 else 1.0
    step = width / max(1, len(points) - 1)
    coords = []
    for index, (_, value) in enumerate(points):
        x = index * step
        y = height - (value / top) * (height - 20) - 8
        coords.append(f"{x:.1f},{y:.1f}")
    line = " ".join(coords)
    threshold_svg = ""
    if threshold is not None and threshold <= top:
        y = height - (threshold / top) * (height - 20) - 8
        threshold_svg = (
            f'<line x1="0" y1="{y:.1f}" x2="{width}" y2="{y:.1f}" '
            f'stroke="#dc2626" stroke-width="1.5" stroke-dasharray="6 4" />'
            f'<text x="6" y="{y - 4:.1f}" class="thr">threshold {threshold:g} {unit}</text>'
        )
    labels = ""
    if points:
        labels = (
            f'<text x="0" y="{height + 14}" class="axis">{points[0][0]}</text>'
            f'<text x="{width - 34}" y="{height + 14}" class="axis">{points[-1][0]}</text>'
            f'<text x="{width - 60}" y="12" class="axis">max {top:g} {unit}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height + 20}" class="chart" role="img">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{line}" />'
        f"{threshold_svg}{labels}</svg>"
    )


def svg_bars(points: list[tuple[str, float]], unit: str, width: int = 560, height: int = 170) -> str:
    if not points:
        return f'<div class="empty">Không có dữ liệu trong cửa sổ thời gian này</div>'
    values = [value for _, value in points]
    top = max(values) if max(values) > 0 else 1.0
    slot = width / max(1, len(points))
    bars = []
    for index, (_, value) in enumerate(points):
        bar_height = (value / top) * (height - 24)
        x = index * slot + 1
        y = height - bar_height - 6
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(1.0, slot - 2):.1f}" '
            f'height="{bar_height:.1f}" fill="#0ea5e9" />'
        )
    labels = (
        f'<text x="0" y="{height + 14}" class="axis">{points[0][0]}</text>'
        f'<text x="{width - 34}" y="{height + 14}" class="axis">{points[-1][0]}</text>'
        f'<text x="{width - 70}" y="12" class="axis">max {top:g} {unit}</text>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height + 20}" class="chart" role="img">'
        f'{"".join(bars)}{labels}</svg>'
    )


QUESTION_BY_ID = {
    "latency": "Request có chậm không? P50/P95/P99 và TTFT đang ở mức nào?",
    "traffic": "Hệ thống đang nhận bao nhiêu request theo thời gian?",
    "errors": "Error rate có tăng không, retrieval có đang fail không?",
    "cost": "Chi phí có tăng bất thường không?",
    "tokens": "Input/output token có dài bất thường không?",
    "quality": "Quality proxy có giảm dưới mức chấp nhận được không?",
}


def build_panels(config: dict, events: list[dict], minutes: int) -> tuple[list[dict], dict]:
    selected, start, end = window_events(events, minutes)
    keys = minute_keys(start, end)
    grouped = group_by_minute(selected)
    by_id = {panel["id"]: panel for panel in config["panels"]}
    summary: dict = {
        "window_minutes": minutes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records_in_window": len(selected),
        "records_total": len(events),
    }
    panels: list[dict] = []

    def add(pid: str, chart: str, stats: list[tuple[str, str]], passed: bool) -> None:
        cfg = by_id[pid]
        threshold = cfg["threshold"]
        panels.append(
            {
                "id": pid,
                "title": cfg["title"],
                "unit": cfg["unit"],
                "question": QUESTION_BY_ID.get(pid, ""),
                "source": cfg["source"],
                "threshold_text": (
                    f"{threshold['aggregation']} {threshold['operator']} "
                    f"{threshold['value']} {cfg['unit']}"
                ),
                "passed": passed,
                "chart": chart,
                "stats": stats,
            }
        )

    sent = [event for event in selected if event.get("event") == "response_sent"]
    received = [event for event in selected if event.get("event") == "request_received"]
    failed = [event for event in selected if event.get("event") == "request_failed"]

    latencies = [float(event["latency_ms"]) for event in sent if event.get("latency_ms") is not None]
    ttfts = [float(event["ttft_ms"]) for event in sent if event.get("ttft_ms") is not None]
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    ttft_p95 = percentile(ttfts, 95)
    summary.update(
        {"latency_p50_ms": p50, "latency_p95_ms": p95, "latency_p99_ms": p99, "ttft_p95_ms": ttft_p95}
    )
    latency_series = [
        (
            bucket_label(key),
            percentile(
                [
                    float(event["latency_ms"])
                    for event in grouped.get(key, [])
                    if event.get("latency_ms") is not None
                ],
                95,
            ),
        )
        for key in keys
    ]
    latency_limit = float(by_id["latency"]["threshold"]["value"])
    add(
        "latency",
        svg_chart(latency_series, latency_limit, "ms"),
        [
            ("P50", f"{p50:.0f} ms"),
            ("P95", f"{p95:.0f} ms"),
            ("P99", f"{p99:.0f} ms"),
            ("TTFT P95", f"{ttft_p95:.0f} ms"),
            ("sample trong cửa sổ", str(len(latencies))),
        ],
        p95 <= latency_limit,
    )

    traffic_series = [(bucket_label(key), float(len(grouped.get(key, [])))) for key in keys]
    traffic_total = len(received)
    per_minute = traffic_total / max(1, minutes)
    peak_per_minute = max([value for _, value in traffic_series] or [0])
    summary.update(
        {
            "request_received": traffic_total,
            "request_per_minute": round(per_minute, 3),
            "request_per_minute_peak": peak_per_minute,
        }
    )
    add(
        "traffic",
        svg_bars(traffic_series, "req/min"),
        [
            ("request nhận được", str(traffic_total)),
            ("trung bình", f"{per_minute:.2f} req/min"),
            ("đỉnh 1 phút", f"{peak_per_minute:.0f} req/min"),
        ],
        peak_per_minute >= float(by_id["traffic"]["threshold"]["value"]),
    )



    error_rate = (len(failed) / len(received) * 100) if received else 0.0
    error_series = []
    for key in keys:
        minute_received = [e for e in grouped.get(key, []) if e.get("event") == "request_received"]
        minute_failed = [e for e in grouped.get(key, []) if e.get("event") == "request_failed"]
        error_series.append(
            (bucket_label(key), len(minute_failed) / max(1, len(minute_received)) * 100)
        )
    retrieval_checked = [event for event in sent if event.get("tool_success") is not None]
    retrieval_ok = [event for event in retrieval_checked if event.get("tool_success")]
    retrieval_rate = (len(retrieval_ok) / len(retrieval_checked) * 100) if retrieval_checked else 0.0
    error_types = Counter(event.get("error_type") or "unknown" for event in failed)
    summary.update(
        {
            "error_rate_pct": round(error_rate, 2),
            "request_failed": len(failed),
            "error_types": dict(error_types),
            "retrieval_success_pct": round(retrieval_rate, 2),
        }
    )
    breakdown = ", ".join(f"{name}={count}" for name, count in error_types.most_common()) or "không có lỗi"
    add(
        "errors",
        svg_bars(error_series, "%"),
        [
            ("error rate", f"{error_rate:.2f} %"),
            ("request_failed", str(len(failed))),
            ("error_type", breakdown),
            ("retrieval success", f"{retrieval_rate:.2f} % ({len(retrieval_ok)}/{len(retrieval_checked)})"),
        ],
        error_rate <= float(by_id["errors"]["threshold"]["value"]),
    )

    costs = [float(event["cost_usd"]) for event in sent if event.get("cost_usd") is not None]
    cost_total = sum(costs)
    cost_series = [
        (
            bucket_label(key),
            sum(float(e["cost_usd"]) for e in grouped.get(key, []) if e.get("cost_usd") is not None),
        )
        for key in keys
    ]
    summary.update(
        {"cost_usd_total": round(cost_total, 6), "cost_usd_avg": round(mean(costs), 6) if costs else 0.0}
    )
    add(
        "cost",
        svg_chart(cost_series, None, "usd"),
        [
            ("tổng cost", f"${cost_total:.6f}"),
            ("trung bình/request", f"${(mean(costs) if costs else 0.0):.6f}"),
            ("số request tính cost", str(len(costs))),
        ],
        cost_total <= float(by_id["cost"]["threshold"]["value"]),
    )

    tokens_in = sum(int(event["tokens_in"]) for event in sent if event.get("tokens_in") is not None)
    tokens_out = sum(int(event["tokens_out"]) for event in sent if event.get("tokens_out") is not None)
    tokens_in_series = [
        (
            bucket_label(key),
            sum(float(e["tokens_in"]) for e in grouped.get(key, []) if e.get("tokens_in") is not None),
        )
        for key in keys
    ]
    tokens_out_series = [
        (
            bucket_label(key),
            sum(float(e["tokens_out"]) for e in grouped.get(key, []) if e.get("tokens_out") is not None),
        )
        for key in keys
    ]
    summary.update({"tokens_in_total": tokens_in, "tokens_out_total": tokens_out})
    tokens_limit = float(by_id["tokens"]["threshold"]["value"])
    add(
        "tokens",
        svg_chart(tokens_in_series, tokens_limit, "tokens")
        + svg_chart(tokens_out_series, tokens_limit, "tokens", color="#f97316"),
        [
            ("tokens_in tổng", str(tokens_in)),
            ("tokens_out tổng", str(tokens_out)),
            ("tổng", str(tokens_in + tokens_out)),
            ("biểu đồ", "trên: input tokens, dưới: output tokens"),
        ],
        (tokens_in + tokens_out) <= tokens_limit,
    )

    qualities = [float(event["quality_score"]) for event in sent if event.get("quality_score") is not None]
    quality_avg = mean(qualities) if qualities else 0.0
    quality_series = []
    for key in keys:
        minute_scores = [
            float(e["quality_score"]) for e in grouped.get(key, []) if e.get("quality_score") is not None
        ]
        quality_series.append((bucket_label(key), mean(minute_scores) if minute_scores else 0.0))
    summary.update({"quality_avg": round(quality_avg, 4), "quality_samples": len(qualities)})
    add(
        "quality",
        svg_chart(quality_series, float(by_id["quality"]["threshold"]["value"]), "score"),
        [
            ("quality trung bình", f"{quality_avg:.3f}"),
            ("số mẫu", str(len(qualities))),
            ("thấp nhất", f"{min(qualities):.2f}" if qualities else "n/a"),
            ("cao nhất", f"{max(qualities):.2f}" if qualities else "n/a"),
        ],
        quality_avg >= float(by_id["quality"]["threshold"]["value"]),
    )

    summary["window_start_local"] = start.astimezone(LOCAL_TZ).isoformat()
    summary["window_end_local"] = end.astimezone(LOCAL_TZ).isoformat()
    return panels, summary


def render_html(
    config: dict, panels: list[dict], summary: dict, refresh_seconds: int, columns: int = 2
) -> str:
    cards = []
    for panel in panels:
        status_class = "ok" if panel["passed"] else "bad"
        status_text = "ĐẠT" if panel["passed"] else "VƯỢT NGƯỠNG"
        rows = "".join(
            f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in panel["stats"]
        )
        cards.append(
            f"""
    <section class="panel">
      <header>
        <h2>{panel['title']}</h2>
        <p class="question">{panel['question']}</p>
      </header>
      <div class="chips">
        <span class="chip">đơn vị: {panel['unit']}</span>
        <span class="chip">threshold: {panel['threshold_text']}</span>
        <span class="chip {status_class}">{status_text}</span>
      </div>
      {panel['chart']}
      <table>{rows}</table>
      <footer>nguồn: {panel['source']}</footer>
    </section>"""
        )

    start = summary.get("window_start_local", "")[:19].replace("T", " ")
    end = summary.get("window_end_local", "")[:19].replace("T", " ")
    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8" />
<meta http-equiv="refresh" content="{refresh_seconds}" />
<title>{config['title']} — dashboard runtime</title>
<style>
  body {{ margin: 0; padding: 18px 22px 32px; background: #f5f7fa; color: #111827;
         font-family: "Segoe UI", Roboto, Arial, sans-serif; }}
  h1 {{ margin: 0 0 4px; font-size: 20px; }}
  .meta {{ font-size: 12.5px; color: #4b5563; margin-bottom: 14px; line-height: 1.6; }}
  .meta b {{ color: #111827; }}
  .grid {{ display: grid; grid-template-columns: repeat({columns}, minmax(420px, 1fr)); gap: 14px; }}
  .panel {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 14px 8px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, .05); }}
  .panel h2 {{ margin: 0; font-size: 15px; }}
  .question {{ margin: 2px 0 0; font-size: 11.5px; color: #6b7280; }}
  .chips {{ margin: 8px 0 4px; display: flex; flex-wrap: wrap; gap: 6px; font-size: 11.5px; }}
  .chip {{ background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 2px 9px; }}
  .chip.ok {{ background: #dcfce7; color: #166534; }}
  .chip.bad {{ background: #fee2e2; color: #991b1b; }}
  .chart {{ width: 100%; height: auto; display: block; }}
  .axis {{ font-size: 10px; fill: #6b7280; }}
  .thr {{ font-size: 10px; fill: #dc2626; }}
  .empty {{ font-size: 12px; color: #9ca3af; padding: 18px 0; text-align: center; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 12px; }}
  th {{ text-align: left; font-weight: 500; color: #4b5563; padding: 2px 0; }}
  td {{ text-align: right; font-variant-numeric: tabular-nums; color: #111827; padding: 2px 0; }}
  footer {{ margin-top: 6px; font-size: 10.5px; color: #9ca3af; }}
</style>
</head>
<body>
  <h1>{config['title']}</h1>
  <div class="meta">
    <b>Time range:</b> {start} → {end} ({summary['window_minutes']} phút) &nbsp;|&nbsp;
    <b>Refresh:</b> {refresh_seconds}s &nbsp;|&nbsp; <b>Records trong cửa sổ:</b> {summary['records_in_window']}
    / {summary['records_total']} &nbsp;|&nbsp; <b>Generated (UTC):</b> {summary['generated_at'][:19].replace('T', ' ')}<br />
    Contract: config/dashboard.yaml &nbsp;|&nbsp; Nguồn dữ liệu: data/logs.jsonl &nbsp;|&nbsp;
    <b>P95:</b> {summary.get('latency_p95_ms', 0):.0f} ms &nbsp;|&nbsp;
    <b>Error rate:</b> {summary.get('error_rate_pct', 0):.2f}% &nbsp;|&nbsp;
    <b>Retrieval success:</b> {summary.get('retrieval_success_pct', 0):.2f}% &nbsp;|&nbsp;
    <b>Quality avg:</b> {summary.get('quality_avg', 0):.3f} &nbsp;|&nbsp;
    <b>Cost:</b> ${summary.get('cost_usd_total', 0):.6f}
  </div>
  <div class="grid">{''.join(cards)}</div>
</body>
</html>
"""



class DashboardHandler(BaseHTTPRequestHandler):
    config: dict = {}
    window_minutes: int = 60
    refresh_seconds: int = 30
    columns: int = 2

    def _render(self) -> tuple[str, dict]:
        events = load_events(LOG_PATH)
        panels, summary = build_panels(self.config, events, self.window_minutes)
        return (
            render_html(self.config, panels, summary, self.refresh_seconds, self.columns),
            summary,
        )

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - theo API cua BaseHTTPRequestHandler
        html, summary = self._render()
        if self.path.startswith("/summary"):
            self._send(json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")
            return
        self._send(html.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, *_args) -> None:
        return


def main() -> None:
    configure_utf8_stdio()
    os.chdir(REPO_ROOT)
    config = load_panel_config()

    parser = argparse.ArgumentParser(description="Dashboard runtime 6 panel cho CP2")
    parser.add_argument(
        "--window-minutes", type=int, default=int(config.get("time_range_minutes", 60))
    )
    parser.add_argument("--refresh", type=int, default=int(config.get("refresh_seconds", 30)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--once", action="store_true", help="chi in snapshot so lieu roi thoat")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--columns", type=int, default=2, help="so cot panel (2 hoac 3)")
    parser.add_argument("--html-out", help="ghi them file HTML tinh de doi chieu")
    args = parser.parse_args()

    events = load_events(LOG_PATH)
    panels, summary = build_panels(config, events, args.window_minutes)
    html = render_html(config, panels, summary, args.refresh, args.columns)
    if args.html_out:
        Path(args.html_out).write_text(html, encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nSo panel: {len(panels)} | nguon: {LOG_PATH}")
    if args.once:
        return

    DashboardHandler.config = config
    DashboardHandler.window_minutes = args.window_minutes
    DashboardHandler.refresh_seconds = args.refresh
    DashboardHandler.columns = args.columns
    url = f"http://{args.host}:{args.port}/"
    print(f"Dashboard runtime: {url} (refresh {args.refresh}s, window {args.window_minutes} phut)")
    if not args.no_browser:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass
    ThreadingHTTPServer((args.host, args.port), DashboardHandler).serve_forever()


if __name__ == "__main__":
    main()

