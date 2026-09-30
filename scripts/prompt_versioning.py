"""CP2 helper: prompt v1/v2 trên Langfuse, promote/rollback label `production`, tạo trace theo label.

Script đọc key từ `.env` (không hard-code secret) và dùng chính app trong repo
(`app.main:app`) nên trace/log sinh ra giống hệt luồng `/chat` thật.

Ví dụ:
    python scripts/prompt_versioning.py init
    python scripts/prompt_versioning.py status
    python scripts/prompt_versioning.py run --label baseline --requests 2
    python scripts/prompt_versioning.py promote --version 2
    python scripts/prompt_versioning.py run --label production --requests 2
    python scripts/prompt_versioning.py rollback --version 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=False)

from app.cli import configure_utf8_stdio  # noqa: E402
from app.prompt_management import DEFAULT_PROMPT_TEMPLATE  # noqa: E402

PROMPT_NAME = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
PRODUCTION_LABEL = "production"
BASELINE_LABEL = "baseline"
CANDIDATE_LABEL = "candidate"
RUN_MESSAGE = "Explain why metrics traces and logs work together"

# v1 giữ nguyên template local để trace ghi prompt_source=langfuse với version 1.
V1_PROMPT = DEFAULT_PROMPT_TEMPLATE
V2_PROMPT = (
    DEFAULT_PROMPT_TEMPLATE
    + "\nTra loi ngan gon toi da 2 cau va neu ro tai lieu nao dung de tra loi."
)
OBSERVATION_FIELDS = "core,basic,metadata,prompt,usage,model,metrics,trace_context"


def _client():
    from langfuse import Langfuse

    return Langfuse()


def _base_url() -> str:
    return os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com").rstrip("/")


def _project_id(client) -> str:
    try:
        return client.api.projects.get().data[0].id
    except Exception:
        return ""


def _trace_url(client, trace_id: str) -> str:
    project_id = _project_id(client)
    if not project_id:
        return f"{_base_url()}/trace/{trace_id}"
    return f"{_base_url()}/project/{project_id}/traces/{trace_id}"


def _all_versions(client) -> list[int]:
    for meta in client.api.prompts.list(name=PROMPT_NAME).data:
        if meta.name == PROMPT_NAME:
            return sorted(meta.versions)
    return []


def _labels_of_version(client, version: int) -> list[str]:
    """Label that su cua mot version (bo label he thong 'latest')."""
    prompt = client.api.prompts.get(PROMPT_NAME, version=version)
    return [label for label in list(prompt.labels) if label != "latest"]


def _version_of_label(client, label: str) -> int | None:
    try:
        prompt = client.api.prompts.get(PROMPT_NAME, label=label)
    except Exception:
        return None
    return int(prompt.version)


def _print_prompt_state(client) -> None:
    metas = [m for m in client.api.prompts.list().data if m.name == PROMPT_NAME]
    if not metas:
        print(f"Prompt '{PROMPT_NAME}': chua ton tai tren project nay.")
        return
    meta = metas[0]
    print(f"Prompt '{PROMPT_NAME}' ({meta.type}) | versions={sorted(meta.versions)}")
    for version in sorted(meta.versions):
        labels = _labels_of_version(client, version)
        print(f"  - v{version}: labels={labels or ['<khong co label>']}")
    for label in (BASELINE_LABEL, CANDIDATE_LABEL, PRODUCTION_LABEL):
        resolved = _version_of_label(client, label)
        print(f"  - label '{label}' -> version {resolved if resolved is not None else '(khong ton tai)'}")


def cmd_init(client, _args: argparse.Namespace) -> None:
    metas = [m for m in client.api.prompts.list().data if m.name == PROMPT_NAME]
    if metas:
        print(f"Prompt '{PROMPT_NAME}' da ton tai, khong tao lai. Trang thai hien tai:")
        _print_prompt_state(client)
        return

    v1 = client.create_prompt(
        name=PROMPT_NAME,
        type="text",
        prompt=V1_PROMPT,
        labels=[BASELINE_LABEL, PRODUCTION_LABEL],
        commit_message="v1 baseline: dung template local, gan baseline + production",
    )
    v2 = client.create_prompt(
        name=PROMPT_NAME,
        type="text",
        prompt=V2_PROMPT,
        labels=[CANDIDATE_LABEL],
        commit_message="v2 candidate: them rang buoc do dai/source, gan candidate",
    )
    print(f"Da tao prompt '{PROMPT_NAME}': v{v1.version} labels=[{BASELINE_LABEL}, {PRODUCTION_LABEL}]")
    print(f"Da tao prompt '{PROMPT_NAME}': v{v2.version} labels=[{CANDIDATE_LABEL}]")
    _print_prompt_state(client)


def _metadata_of(observation) -> dict:
    raw = getattr(observation, "metadata", None)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw[:200]}
    return dict(raw or {})


def _observation_index(client, session_ids: set[str], minutes: int = 15) -> dict:
    now = datetime.now(timezone.utc)
    found: dict = {}
    for attempt in range(5):
        response = client.api.observations.get_many(
            from_start_time=now - timedelta(minutes=minutes),
            to_start_time=now + timedelta(minutes=1),
            is_root_observation=True,
            fields=OBSERVATION_FIELDS,
            expand_metadata="metadata",
            limit=100,
        )
        found = {obs.session_id: obs for obs in response.data if obs.session_id in session_ids}
        if len(found) >= len(session_ids):
            return found
        if attempt < 4:
            time.sleep(3)
    return found


def _send_requests(label: str, count: int, feature: str, stamp: str) -> list[dict]:
    import httpx

    os.environ["LANGFUSE_PROMPT_LABEL"] = label
    from app.main import app

    async def _run() -> list[dict]:
        transport = httpx.ASGITransport(app=app)
        results: list[dict] = []
        async with httpx.AsyncClient(
            transport=transport, base_url="http://prompt-versioning", timeout=30.0
        ) as client:
            for index in range(count):
                session_id = f"pv-{label}-{stamp}-{index + 1}"
                payload = {
                    "user_id": f"u-pv-{label}",
                    "session_id": session_id,
                    "feature": feature,
                    "message": RUN_MESSAGE,
                }
                response = await client.post("/chat", json=payload)
                response.raise_for_status()
                body = response.json()
                results.append(
                    {
                        "session_id": session_id,
                        "correlation_id": body["correlation_id"],
                        "latency_ms": body["latency_ms"],
                        "tokens_in": body["tokens_in"],
                        "tokens_out": body["tokens_out"],
                        "cost_usd": body["cost_usd"],
                        "quality_score": body["quality_score"],
                    }
                )
        return results

    return asyncio.run(_run())


def cmd_run(client, args: argparse.Namespace) -> None:
    from langfuse import get_client

    resolved = _version_of_label(client, args.label)
    print(f"Label '{args.label}' -> version {resolved} | prompt '{PROMPT_NAME}'")
    print(f"Input co dinh cho moi label: {RUN_MESSAGE!r}")

    results = _send_requests(args.label, args.requests, args.feature, time.strftime("%H%M%S"))
    get_client().flush()

    observations = _observation_index(client, {item["session_id"] for item in results})
    header = (
        f"{'session_id':<18} {'correlation_id':<16} {'trace_id':<34} "
        f"{'prompt':<24} {'source':<14} {'latency_ms':>10}"
    )
    print("")
    print(header)
    print("-" * len(header))
    for item in results:
        observation = observations.get(item["session_id"])
        metadata = _metadata_of(observation) if observation else {}
        prompt_info = (
            f"{metadata.get('prompt_name')}/{metadata.get('prompt_label')}/"
            f"v{metadata.get('prompt_version')}"
        )
        print(
            f"{item['session_id']:<18} {item['correlation_id']:<16} "
            f"{str(getattr(observation, 'trace_id', '(chua ingest)')):<34} "
            f"{prompt_info:<24} {str(metadata.get('prompt_source')):<14} {item['latency_ms']:>10}"
        )

    print("")
    print("Mo cac trace sau tren Langfuse:")
    for item in results:
        trace_id = getattr(observations.get(item["session_id"]), "trace_id", None)
        if trace_id:
            print(f"  - {item['correlation_id']} -> {_trace_url(client, trace_id)}")
    print("")
    print("So lieu de dien vao REPORT.md (muc 5):")
    for index, item in enumerate(results, start=1):
        observation = observations.get(item["session_id"])
        metadata = _metadata_of(observation) if observation else {}
        print(
            f"  [{index}] label={args.label} prompt_version={metadata.get('prompt_version')} "
            f"trace_id={getattr(observation, 'trace_id', None)} "
            f"correlation_id={item['correlation_id']} "
            f"tokens={item['tokens_in']}/{item['tokens_out']} cost_usd={item['cost_usd']}"
        )


def cmd_status(client, _args: argparse.Namespace) -> None:
    _print_prompt_state(client)
    print("")
    now = datetime.now(timezone.utc)
    response = client.api.observations.get_many(
        from_start_time=now - timedelta(hours=3),
        to_start_time=now + timedelta(minutes=1),
        is_root_observation=True,
        fields=OBSERVATION_FIELDS,
        expand_metadata="metadata",
        limit=50,
    )
    roots = sorted(response.data, key=lambda obs: obs.start_time, reverse=True)[:10]
    print(f"Root observations gan nhat ({len(roots)}):")
    for observation in roots:
        metadata = _metadata_of(observation)
        print(
            f"  {observation.start_time} | {observation.name} | trace={observation.trace_id} | "
            f"session={observation.session_id} | prompt={metadata.get('prompt_name')}/"
            f"{metadata.get('prompt_label')}/v{metadata.get('prompt_version')} | "
            f"source={metadata.get('prompt_source')} | version_field={observation.version}"
        )
    if roots:
        print("")
        print("Metadata day du cua root moi nhat (doi chieu voi anh 08-trace-metadata):")
        print(json.dumps(_metadata_of(roots[0]), ensure_ascii=False, indent=2))


def main() -> None:
    configure_utf8_stdio()
    os.chdir(REPO_ROOT)

    parser = argparse.ArgumentParser(description="CP2 prompt versioning helper")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="tao prompt v1 (baseline, production) va v2 (candidate)")

    run_parser = sub.add_parser("run", help="gui request that qua app voi mot label")
    run_parser.add_argument(
        "--label",
        default=os.getenv("LANGFUSE_PROMPT_LABEL", PRODUCTION_LABEL),
        help="label cua prompt trong Langfuse (baseline/candidate/production)",
    )
    run_parser.add_argument("--requests", type=int, default=2)
    run_parser.add_argument("--feature", default="qa")

    promote_parser = sub.add_parser("promote", help="chuyen label production sang version moi")
    promote_parser.add_argument("--version", type=int, required=True)

    rollback_parser = sub.add_parser("rollback", help="dua label production ve version cu")
    rollback_parser.add_argument("--version", type=int, required=True)

    sub.add_parser("status", help="in prompt versions/labels va cac root trace gan nhat")

    args = parser.parse_args()
    client = _client()

    if args.command == "init":
        cmd_init(client, args)
    elif args.command == "run":
        cmd_run(client, args)
    elif args.command == "status":
        cmd_status(client, args)
    elif args.command == "promote":
        args.action = "promote"
        cmd_set_production(client, args)
    elif args.command == "rollback":
        args.action = "rollback"
        cmd_set_production(client, args)


def cmd_set_production(client, args: argparse.Namespace) -> None:
    action = args.action
    version = args.version
    labels = _labels_of_version(client, version)
    if not labels:
        raise SystemExit(f"Khong tim thay version {version} cua prompt '{PROMPT_NAME}'.")

    current = _version_of_label(client, PRODUCTION_LABEL)
    client.update_prompt(
        name=PROMPT_NAME,
        version=version,
        new_labels=sorted({*labels, PRODUCTION_LABEL}),
    )
    for other in _all_versions(client):
        if other == version:
            continue
        other_labels = _labels_of_version(client, other)
        if PRODUCTION_LABEL in other_labels:
            client.update_prompt(
                name=PROMPT_NAME,
                version=other,
                new_labels=[lbl for lbl in other_labels if lbl != PRODUCTION_LABEL],
            )

    print(
        f"{action.upper()}: label '{PRODUCTION_LABEL}' "
        f"v{current} -> v{version} (prompt {PROMPT_NAME})"
    )
    _print_prompt_state(client)


if __name__ == "__main__":
    main()

