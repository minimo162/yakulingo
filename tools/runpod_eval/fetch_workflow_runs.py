#!/usr/bin/env python3
"""Fetch GitHub Actions runs for RunPod workflows and print a Markdown summary."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib import error, request

API_BASE = "https://api.github.com"
JST = timezone(timedelta(hours=9))
WORKFLOWS: tuple[tuple[str, str], ...] = (
    ("runpod-morning-resume", "runpod-morning-resume.yml"),
    ("runpod-window-stop", "runpod-window-stop.yml"),
)


@dataclass
class WorkflowRun:
    run_id: int
    event: str
    status: str
    conclusion: str
    created_at_utc: datetime
    head_sha: str
    html_url: str

    @property
    def created_at_jst(self) -> datetime:
        return self.created_at_utc.astimezone(JST)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch runpod workflow runs from GitHub Actions.")
    parser.add_argument("--repo", default="minimo162/yakulingo", help="owner/repo (default: minimo162/yakulingo)")
    parser.add_argument("--date-jst", default="", help="target date in JST (YYYY-MM-DD). default: today (JST)")
    parser.add_argument("--per-page", type=int, default=20, help="GitHub API per_page for each workflow")
    parser.add_argument("--max-rows", type=int, default=5, help="max rows per workflow in output")
    parser.add_argument("--json-out", default="", help="optional path to save filtered runs as JSON")
    return parser.parse_args()


def resolve_target_date(raw: str) -> date:
    if raw:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    return datetime.now(JST).date()


def fetch_json(url: str, token: str) -> dict:
    req = request.Request(url, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "yakulingo-runpod-eval")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"GitHub API error {exc.code} for {url}: {body[:500]}") from exc


def parse_run(item: dict) -> WorkflowRun:
    created_raw = str(item.get("created_at") or "")
    created = datetime.strptime(created_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return WorkflowRun(
        run_id=int(item.get("id") or 0),
        event=str(item.get("event") or ""),
        status=str(item.get("status") or ""),
        conclusion=str(item.get("conclusion") or ""),
        created_at_utc=created,
        head_sha=str(item.get("head_sha") or ""),
        html_url=str(item.get("html_url") or ""),
    )


def fetch_workflow_runs(
    repo: str,
    workflow_file: str,
    per_page: int,
    token: str,
) -> list[WorkflowRun]:
    url = f"{API_BASE}/repos/{repo}/actions/workflows/{workflow_file}/runs?per_page={per_page}"
    data = fetch_json(url, token=token)
    runs_raw = data.get("workflow_runs") or []
    return [parse_run(item) for item in runs_raw]


def filter_by_jst_date(runs: list[WorkflowRun], target: date) -> list[WorkflowRun]:
    return [run for run in runs if run.created_at_jst.date() == target]


def to_dict(run: WorkflowRun) -> dict:
    return {
        "id": run.run_id,
        "event": run.event,
        "status": run.status,
        "conclusion": run.conclusion,
        "created_at_utc": run.created_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_at_jst": run.created_at_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
        "head_sha": run.head_sha,
        "html_url": run.html_url,
    }


def print_markdown(
    target: date,
    grouped_runs: dict[str, list[WorkflowRun]],
    max_rows: int,
) -> None:
    print(f"## RunPod 自動化ログ（{target.isoformat()} JST）[GitHub API自動取得]")
    for workflow_name, _ in WORKFLOWS:
        print()
        print(f"- {workflow_name}")
        runs = grouped_runs.get(workflow_name, [])
        if not runs:
            print("  - 該当runなし")
            continue
        for run in runs[:max_rows]:
            created = run.created_at_jst.strftime("%Y-%m-%d %H:%M:%S JST")
            short_sha = run.head_sha[:12]
            print(
                "  - "
                f"{created} | id=`{run.run_id}` | event=`{run.event}` | "
                f"status=`{run.status}` | conclusion=`{run.conclusion}` | sha=`{short_sha}`"
            )
            print(f"    - url: {run.html_url}")


def main() -> None:
    args = parse_args()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    target = resolve_target_date(args.date_jst)

    grouped: dict[str, list[WorkflowRun]] = {}
    for workflow_name, workflow_file in WORKFLOWS:
        all_runs = fetch_workflow_runs(
            repo=args.repo,
            workflow_file=workflow_file,
            per_page=args.per_page,
            token=token,
        )
        grouped[workflow_name] = filter_by_jst_date(all_runs, target)

    print_markdown(target=target, grouped_runs=grouped, max_rows=args.max_rows)

    if args.json_out:
        path = Path(args.json_out)
        payload = {
            "repo": args.repo,
            "target_date_jst": target.isoformat(),
            "workflows": {
                workflow_name: [to_dict(run) for run in grouped.get(workflow_name, [])]
                for workflow_name, _ in WORKFLOWS
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - CLI entrypoint guard
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
