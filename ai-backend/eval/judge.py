"""LLM judge for response quality only (SPEC §11.4): clarity, tone, language correctness.

Everything else is graded deterministically. The judge must be a different model from the agent
under test, and it counts only after validation against ≥ 30 human-labelled cases:

    python -m eval.judge score eval/runs/<run>        # judge an existing run
    python -m eval.judge agreement eval/runs/<run>/judge_validation.csv

The labelling sheet stays in the run folder (gitignored): it holds whole conversations.
"""

from __future__ import annotations

import asyncio
import csv
import json
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx

from ai_backend.config import load_model_registry, load_policy_config
from ai_backend.llm.registry import build_chat_model
from ai_backend.settings import Settings

CRITERIA = ("clarity", "tone", "language")
SAMPLE_FOR_HUMANS = 40
RUBRIC = """You grade one reply of a bank's customer-service assistant. Judge only these, 1 (bad) to 5 (excellent):

- clarity: the reply answers what the customer asked, is easy to follow and short enough for a chat.
- tone: polite, professional and calm; no blame, no jargon, no internal codes or system details.
- language: written in the customer's language ({language}: Spanish or Brazilian Portuguese), grammatical and natural.

Do not judge whether facts are correct (checked elsewhere). Reply with JSON only:
{{"clarity": <1-5>, "tone": <1-5>, "language": <1-5>, "comment": "<one short sentence>"}}

Conversation:
{conversation}
"""


def _conversation(turns: list[dict[str, Any]]) -> str:
    return "\n".join(f"Customer: {t['user']}\nAssistant: {t['reply']}" for t in turns)


def _parse(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not all(isinstance(data.get(c), int) and 1 <= data[c] <= 5 for c in CRITERIA):
        return None
    return data


def _judged(system: str) -> bool:
    """The full system and its model variants (S, S@<model>)."""
    return system == "S" or system.startswith("S@")


async def judge_run(
    raw: list[dict[str, Any]], settings: Settings, scenarios: list
) -> list[dict[str, Any]]:
    models = load_model_registry(settings.models_config_path)
    policy = load_policy_config(settings.policy_config_path)
    agents = {settings.agent_model} | {
        r["result"]["system"].split("@", 1)[1] for r in raw if "@" in r["result"]["system"]
    }
    if settings.judge_model in agents:
        raise SystemExit("the judge must be a different model from the agents under test")
    llm = build_chat_model(
        models.get(settings.judge_model),
        settings,
        policy.timeouts_seconds.llm,
        policy.retries.max,
        httpx.AsyncClient(timeout=policy.timeouts_seconds.llm),
    )
    language = {s.id: s.language for s in scenarios}
    rows = [
        r
        for r in raw
        if _judged(r["result"]["system"])
        and r["result"]["repeat"] == 0
        and r["result"]["outcome"] in ("answered", "refused")
        and r["transcript"]["turns"]
    ]
    gate = asyncio.Semaphore(4)

    async def one(r: dict[str, Any]) -> dict[str, Any]:
        sid = r["result"]["scenario_id"]
        prompt = RUBRIC.format(
            language=language.get(sid, "es"), conversation=_conversation(r["transcript"]["turns"])
        )
        async with gate:
            try:
                reply = await llm.ainvoke(prompt)
                scores = _parse(
                    reply.content if isinstance(reply.content, str) else str(reply.content)
                )
            except Exception:  # an unscored case is reported as such
                scores = None
        return {
            "system": r["result"]["system"],
            "scenario_id": sid,
            "language": language.get(sid),
            "judge_model": settings.judge_model,
            "conversation": _conversation(r["transcript"]["turns"]),
            "scores": scores,
        }

    return await asyncio.gather(*(one(r) for r in rows))


def save_judge(run_dir: Path, rows: list[dict[str, Any]]) -> None:
    with (run_dir / "judge.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_validation_sheet(rows, run_dir / "judge_validation.csv")


def load_judge(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "judge.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_validation_sheet(rows: list[dict[str, Any]], path: Path, seed: int = 7) -> None:
    scored = [r for r in rows if r.get("scores")]
    sample = random.Random(seed).sample(scored, min(SAMPLE_FOR_HUMANS, len(scored)))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["system", "scenario_id", "language", "conversation"]
            + [f"judge_{c}" for c in CRITERIA]
            + [f"human_{c}" for c in CRITERIA]
            + ["human_notes"]
        )
        for r in sample:
            writer.writerow(
                [r["system"], r["scenario_id"], r["language"], r["conversation"]]
                + [r["scores"][c] for c in CRITERIA]
                + ["", "", "", ""]
            )


def agreement(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if all(r[f"human_{c}"].strip() for c in CRITERIA)]
    if len(rows) < 30:
        raise SystemExit(f"{len(rows)} labelled rows; SPEC §11.4 needs at least 30")
    result: dict[str, Any] = {"labelled": len(rows)}
    for c in CRITERIA:
        judge = [int(r[f"judge_{c}"]) for r in rows]
        human = [int(r[f"human_{c}"]) for r in rows]
        exact = sum(j == h for j, h in zip(judge, human, strict=True)) / len(rows)
        within = sum(abs(j - h) <= 1 for j, h in zip(judge, human, strict=True)) / len(rows)
        try:
            rho = statistics.correlation(judge, human, method="ranked")
        except statistics.StatisticsError:
            rho = None
        result[c] = {
            "exact": round(exact, 3),
            "within_1": round(within, 3),
            "spearman": rho and round(rho, 3),
        }
    return result


def _score(run_dir: Path) -> None:
    from eval import scenarios as scenario_files

    root = Path(__file__).resolve().parents[1]
    settings = Settings(_env_file=root / ".env")
    meta = json.loads((run_dir / "meta.json").read_text())
    raw = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text().splitlines()]
    rows = asyncio.run(judge_run(raw, settings, scenario_files.load(meta["split"])))
    save_judge(run_dir, rows)
    print(f"{sum(bool(r['scores']) for r in rows)}/{len(rows)} scored → {run_dir}/judge.jsonl")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "agreement":
        print(json.dumps(agreement(Path(sys.argv[2])), indent=2))
    elif len(sys.argv) == 3 and sys.argv[1] == "score":
        _score(Path(sys.argv[2]))
    else:
        raise SystemExit(
            "usage: python -m eval.judge score <run dir> | agreement <judge_validation.csv>"
        )
