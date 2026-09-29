"""Run systems × scenarios × repeats, grade them, and write the report (SPEC §11.2).

    python -m eval.runner --systems B0,B1,S --split test --repeats 3

Raw transcripts go to eval/runs/<timestamp>/ (gitignored: full conversations);
the report goes to eval/reports/<timestamp>/ (committed).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog
from langgraph.checkpoint.memory import InMemorySaver

from ai_backend.agent.graph import build_graph
from ai_backend.agent.service import ChatService
from ai_backend.bank.fixture import load_fixture
from ai_backend.classifier.predict import RouteClassifier
from ai_backend.config import load_model_registry, load_policy_config
from ai_backend.conversations.store import MemoryConversationStore
from ai_backend.handoff.store import MemoryHandoffStore
from ai_backend.llm.registry import build_chat_model
from ai_backend.observability.store import MemoryTraceStore
from ai_backend.settings import Settings
from ai_backend.tools.registry import REGISTRY, tool_schemas
from eval import scenarios as scenario_files
from eval.grading import CaseResult, grade
from eval.systems import CaseEnv, FullSystem, KeywordBot, ToolLoopSystem
from eval.transcript import Transcript

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"
REPORTS = ROOT / "eval" / "reports"


def build_systems(names: list[str], settings: Settings, llm: Any = None, classifier: Any = None):
    policy = load_policy_config(settings.policy_config_path)
    models = load_model_registry(settings.models_config_path)
    spec = models.get(settings.agent_model)
    if llm is None and ({"S", "B1"} & set(names)):
        http = httpx.AsyncClient(timeout=policy.timeouts_seconds.llm)
        llm = build_chat_model(
            spec, settings, policy.timeouts_seconds.llm, policy.retries.max, http
        )
    bound = llm.bind_tools(tool_schemas()) if llm is not None else None
    if classifier is None and "S" in names and settings.classifier_path:
        classifier = RouteClassifier.load(settings.classifier_path)
    systems = {}
    if "B0" in names:
        systems["B0"] = KeywordBot()
    if "B1" in names:
        systems["B1"] = ToolLoopSystem(bound, settings.history_end)
    if "S" in names:
        service = ChatService(
            graph=build_graph(InMemorySaver()),
            bank=None,  # set per case
            llm=bound,
            model_key=settings.agent_model,
            model_spec=spec,
            tools=REGISTRY,
            policy=policy,
            conversations=MemoryConversationStore(),
            traces=MemoryTraceStore(),
            handoffs=MemoryHandoffStore(),
            clock=lambda: datetime.now(UTC),
            history_end=settings.history_end,
            classifier=classifier,
        )
        systems["S"] = FullSystem(service)
    return systems, spec


async def run_case(system, scenario, fixture, repeat: int) -> tuple[CaseResult, Transcript]:
    env = CaseEnv(scenario, fixture)
    try:
        transcript = await system.run(env)
    except Exception as exc:  # a crash is a failed case, reported with its cause
        transcript = Transcript(
            scenario.id, system.name, error=f"{type(exc).__name__}: {exc}"[:300]
        )
    return grade(scenario, transcript, repeat), transcript


async def run(
    systems: dict[str, Any],
    cases: list[scenario_files.Scenario],
    fixture,
    repeats: int,
    concurrency: int,
    progress: bool = True,
) -> tuple[list[CaseResult], list[dict[str, Any]]]:
    gate = asyncio.Semaphore(concurrency)
    results: list[CaseResult] = []
    raw: list[dict[str, Any]] = []
    total = len(systems) * len(cases) * repeats
    started = time.perf_counter()

    async def one(name: str, scenario, repeat: int) -> None:
        async with gate:
            result, transcript = await run_case(systems[name], scenario, fixture, repeat)
        results.append(result)
        raw.append({"result": result.to_dict(), "transcript": dataclasses.asdict(transcript)})
        if progress and len(results) % 25 == 0:
            rate = len(results) / (time.perf_counter() - started)
            print(f"  {len(results)}/{total} cases ({rate:.1f}/s)", flush=True)

    await asyncio.gather(
        *(one(name, s, r) for r in range(repeats) for name in systems for s in cases)
    )
    return results, raw


def main() -> None:
    # Trace events are kept in memory per case; don't print them for every node.
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--systems", default="B0,B1,S")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--families", default="", help="comma-separated families (dev only)")
    parser.add_argument(
        "--model",
        default="",
        help="agent model key from models.yaml instead of AGENT_MODEL; systems are named S@<key>",
    )
    parser.add_argument("--judge", action="store_true", help="score S's answers with the judge")
    args = parser.parse_args()

    settings = Settings(_env_file=ROOT / ".env")
    if args.model:
        settings = settings.model_copy(update={"agent_model": args.model})
    cases = scenario_files.load(args.split)
    if args.split == "test":
        scenario_files.check_lock("test", cases)
    elif args.families:
        wanted = set(args.families.split(","))
        cases = [s for s in cases if s.family in wanted]
    names = args.systems.split(",")
    systems, spec = build_systems(names, settings)
    if args.model:
        for system in systems.values():
            if system.name != "B0":  # the keyword bot has no model
                system.name = f"{system.name}@{args.model}"
        systems = {system.name: system for system in systems.values()}
    fixture = load_fixture(ROOT / "eval" / "fixtures" / "data")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    print(
        f"{len(cases)} {args.split} scenarios × {list(systems)} × {args.repeats} repeats, "
        f"agent {spec.model}"
    )
    results, raw = asyncio.run(run(systems, cases, fixture, args.repeats, args.concurrency))

    run_dir = RUNS / f"{stamp}-{args.split}"
    meta = {
        "split": args.split,
        "systems": list(systems),
        "repeats": args.repeats,
        "agent_model": spec.model,
        "scenarios": len(cases),
        "runs": [str(run_dir.relative_to(ROOT))],
    }
    save_run(run_dir, raw, meta)
    judge_rows = None
    if args.judge:
        from eval.judge import judge_run, save_judge

        judge_rows = asyncio.run(judge_run(raw, settings, cases))
        save_judge(run_dir, judge_rows)
    from eval.report import write_report

    out = write_report(results, REPORTS / f"{stamp}-{args.split}", meta, raw, judge_rows)
    print(f"report: {out}")


def save_run(run_dir: Path, raw: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    """Raw transcripts (gitignored: full conversations) and what produced them."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    with (run_dir / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for row in raw:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
