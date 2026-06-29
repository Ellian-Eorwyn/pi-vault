"""Run one served task model over the gold note set and write a graded result.

Only one large model fits in VRAM, so this evaluates a single model per run:

    python -m evals.runners.run_task --model qwen3.5-9b-q6

Switch the served model, re-run with the matching --model key, and report.py
will aggregate every evals/results/task_*.json into one leaderboard.

It drives the *production* stage prompts and validators (vault_agent.llm) so the
scores reflect what the engine actually asks the model to do. Notes are fed with
their folder neutralised (see common.note_for_model) so the model cannot read the
answer off the directory path.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from evals.common import (
    CONFIGS_DIR,
    DEFAULT_VAULT,
    FIXTURES_DIR,
    RESULTS_DIR,
    dump_json,
    load_json,
    load_yaml,
    mean,
    median,
    note_for_model,
    percentile,
    read_note,
)
from evals.graders import constrained, people, refine, summary
from vault_agent.embeddings import EmbeddingClient
from vault_agent.llm import (
    OpenAICompatibleProposalProvider,
    _chat_completion_content,
    validate_stage_proposal,
)
from vault_agent.schema import RECOMMENDED_TOPIC_HUBS

# Stages graded by exact match against gold labels.
CONSTRAINED_FIELDS = ["status", "domain", "source_kind", "capture_type"]


class InstrumentedProvider(OpenAICompatibleProposalProvider):
    """Provider that records per-call latency, token usage, and repair count.

    Overrides only the HTTP leaf so the real prompts (propose/propose_stage) and
    the real repair loop run unchanged; we just observe them.
    """

    def reset(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.elapsed = 0.0
        self.last_content = ""
        # Per-call (prompt_tokens, completion_tokens) so we can report the context
        # high-water mark, not just totals.
        self.calls_usage: list[tuple[int, int]] = []

    def _chat_completion(self, *, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"LLM request failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"LLM request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ValueError("LLM request timed out") from exc
        self.elapsed += time.monotonic() - start
        self.calls += 1
        usage = response_payload.get("usage") or {}
        content = _chat_completion_content(response_payload)
        # Fall back to a chars/4 estimate when the server omits usage, so context
        # sizing still works against any OpenAI-compatible backend.
        prompt_tokens = int(usage.get("prompt_tokens") or max(1, len(prompt) // 4))
        completion_tokens = int(usage.get("completion_tokens") or max(1, len(content) // 4))
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.calls_usage.append((prompt_tokens, completion_tokens))
        self.last_content = content
        return content


def _allowed_folders(vault_root: Path) -> list[tuple[str, str]]:
    """Top-level Memex folders as (path, description) for assign-folder."""
    descriptions = {
        "01 Inbox": "Unsorted captures awaiting triage",
        "02 Journal": "Daily notes, logs, communications",
        "03 Notes": "General knowledge and ideas",
        "04 Sources": "Books, articles, papers, media",
        "05 Projects": "Active and past projects",
        "06 People": "Contacts and authors",
        "07 Organizations": "Institutions and companies",
        "08 Reference": "Reference material",
        "09 Administrative": "Health, finance, legal, household admin",
    }
    folders = []
    for path in sorted(p for p in vault_root.iterdir() if p.is_dir()):
        name = path.name
        if name.startswith(".") or name in {"00 System", "99 Archive"}:
            continue
        folders.append((name, descriptions.get(name, "")))
    return folders


def _stage_call(provider: InstrumentedProvider, *, note_path, note_text, stage,
                allowed_hubs=None, allowed_folders=None) -> dict[str, Any]:
    """Run one stage, capturing parsed output, validity, latency, tokens, repair."""
    provider.reset()
    start = time.monotonic()
    record: dict[str, Any] = {"stage": stage}
    try:
        parsed = provider.propose_stage(
            note_path=note_path,
            note_text=note_text,
            stage=stage,
            allowed_hubs=allowed_hubs,
            allowed_folders=allowed_folders,
        )
        validation = validate_stage_proposal(
            stage,
            parsed,
            allowed_hubs=allowed_hubs,
            allowed_folders=[f[0] for f in (allowed_folders or [])] if allowed_folders else None,
        )
        record.update(
            {
                "ok": True,
                "parsed": parsed,
                "normalized": validation.proposal,
                "valid": validation.valid,
                "errors": validation.errors,
                "first_pass_json": provider.calls == 1,
                "repaired": provider.calls > 1,
            }
        )
    except Exception as exc:  # noqa: BLE001 - record any failure as a data point
        record.update(
            {
                "ok": False,
                "error": str(exc)[:300],
                "first_pass_json": False,
                "repaired": provider.calls > 1,
                "valid": False,
            }
        )
    record["wall_seconds"] = round(time.monotonic() - start, 3)
    record["completion_tokens"] = provider.completion_tokens
    record["prompt_tokens"] = provider.prompt_tokens
    record["api_seconds"] = round(provider.elapsed, 3)
    usage = list(provider.calls_usage)
    record["calls_usage"] = usage
    # Context a single request needed = its prompt + the tokens it generated.
    record["max_call_prompt_tokens"] = max((p for p, _ in usage), default=0)
    record["max_call_total_tokens"] = max((p + c for p, c in usage), default=0)
    return record


ALL_STAGES = (
    "classify-type", "property-values", "summary", "refine-body",
    "assign-folder", "assign-hub", "classify-person",
)


def run(model_key: str, *, vault_root: Path, limit: int | None, embed_url: str | None,
        stages: set[str] | None = None) -> dict[str, Any]:
    cfg = load_yaml(CONFIGS_DIR / "task_models.yaml")
    model_cfg = next((m for m in cfg["models"] if m["key"] == model_key), None)
    if model_cfg is None:
        raise SystemExit(f"unknown model key `{model_key}` (see configs/task_models.yaml)")
    run_stages = set(stages) if stages else set(ALL_STAGES)

    gold = load_json(FIXTURES_DIR / "gold_notes.json")
    notes = gold["notes"][: limit or len(gold["notes"])]
    allowed_folders = _allowed_folders(vault_root)

    provider = InstrumentedProvider(
        base_url=cfg["endpoint"],
        model=model_cfg.get("model", "code"),
        timeout_seconds=int(cfg.get("timeout_seconds", 180)),
        max_input_tokens=int(cfg.get("max_input_tokens", 64000)),
        chars_per_token=int(cfg.get("chars_per_token", 4)),
    )

    per_note: list[dict[str, Any]] = []
    type_items: list[dict[str, Any]] = []
    constrained_records: list[dict[str, Any]] = []
    folder_items: list[dict[str, Any]] = []
    hub_items: list[dict[str, Any]] = []
    person_items: list[dict[str, Any]] = []
    summary_items: list[dict[str, Any]] = []
    refine_items: list[dict[str, Any]] = []
    all_stage_records: list[dict[str, Any]] = []

    for note in notes:
        rel = note["path"]
        labels = note.get("labels", {})
        npath, ntext = note_for_model(vault_root, rel)
        note_out: dict[str, Any] = {"path": rel, "stages": {}}

        # classify-type
        if "classify-type" in run_stages:
            rec = _stage_call(provider, note_path=npath, note_text=ntext, stage="classify-type")
            note_out["stages"]["classify-type"] = rec
            all_stage_records.append(rec)
            if "type" in labels:
                type_items.append({"pred": rec.get("normalized", {}).get("note_type"), "gold": labels["type"]})

        # property-values (status/domain/source_kind/capture_type)
        if "property-values" in run_stages:
            rec = _stage_call(provider, note_path=npath, note_text=ntext, stage="property-values")
            note_out["stages"]["property-values"] = rec
            all_stage_records.append(rec)
            constrained_records.append({"pred": rec.get("normalized", {}), "gold": labels})

        # summary
        if "summary" in run_stages:
            rec = _stage_call(provider, note_path=npath, note_text=ntext, stage="summary")
            note_out["stages"]["summary"] = rec
            all_stage_records.append(rec)
            if note.get("summary"):
                summary_items.append(
                    {"path": rel, "pred": rec.get("normalized", {}).get("summary"), "ref": note["summary"]}
                )

        # refine-body (word preservation against the real, stripped body)
        if "refine-body" in run_stages and note.get("refine"):
            _, body, _ = read_note(vault_root, rel)
            rec = _stage_call(provider, note_path=npath, note_text=ntext, stage="refine-body")
            note_out["stages"]["refine-body"] = rec
            all_stage_records.append(rec)
            refine_items.append(
                {"path": rel, "source": body, "pred": rec.get("normalized", {}).get("body")}
            )

        # assign-folder
        if "assign-folder" in run_stages:
            rec = _stage_call(
                provider, note_path=npath, note_text=ntext, stage="assign-folder",
                allowed_folders=allowed_folders,
            )
            note_out["stages"]["assign-folder"] = rec
            all_stage_records.append(rec)
            if labels.get("folder"):
                folder_items.append({"pred": rec.get("normalized", {}).get("folder"), "gold": labels["folder"]})

        # assign-hub (only when the fixture pins a gold hub)
        if "assign-hub" in run_stages and note.get("hub"):
            rec = _stage_call(
                provider, note_path=npath, note_text=ntext, stage="assign-hub",
                allowed_hubs=RECOMMENDED_TOPIC_HUBS,
            )
            note_out["stages"]["assign-hub"] = rec
            all_stage_records.append(rec)
            pred_hub = (rec.get("normalized", {}).get("parent") or "").strip("[]")
            hub_items.append({"pred": pred_hub, "gold": note["hub"]})

        # classify-person (only for person notes with a pinned kind)
        if "classify-person" in run_stages and note.get("person_kind"):
            rec = _stage_call(provider, note_path=npath, note_text=ntext, stage="classify-person")
            note_out["stages"]["classify-person"] = rec
            all_stage_records.append(rec)
            person_items.append({"pred": rec.get("normalized", {}).get("kind"), "gold": note["person_kind"]})

        per_note.append(note_out)

    # ---- grade ----
    embed = None
    if embed_url:
        client = EmbeddingClient(base_url=embed_url, model="embed")
        try:
            client.embed(["warmup"])
            embed = client.embed
        except Exception:  # noqa: BLE001 - summary cosine is best-effort
            embed = None

    grades: dict[str, Any] = {
        "classify-type": constrained.grade_field(type_items) if type_items else None,
        "property-values": constrained.grade_fields(constrained_records, CONSTRAINED_FIELDS),
        "assign-folder": constrained.grade_field(folder_items) if folder_items else None,
        "assign-hub": constrained.grade_field(hub_items) if hub_items else None,
        "classify-person": people.grade_classify(person_items) if person_items else None,
        "refine-body": refine.grade_refine(refine_items) if refine_items else None,
    }
    if summary_items:
        grades["summary"] = (
            summary.grade_summaries(summary_items, embed)
            if embed
            else {"note": "embed endpoint unavailable; cosine skipped",
                  **summary.grade_summaries(summary_items, lambda xs: [[0.0]] * len(xs))}
        )

    # ---- robustness + speed ----
    latencies = [r["wall_seconds"] for r in all_stage_records]
    valid_flags = [bool(r.get("valid")) for r in all_stage_records]
    first_pass = [bool(r.get("first_pass_json")) for r in all_stage_records]
    completion_tokens = sum(r.get("completion_tokens", 0) for r in all_stage_records)
    api_seconds = sum(r.get("api_seconds", 0.0) for r in all_stage_records)
    robustness = {
        "stage_calls": len(all_stage_records),
        "valid_rate": round(mean([float(x) for x in valid_flags]), 4),
        "first_pass_json_rate": round(mean([float(x) for x in first_pass]), 4),
        "ok_rate": round(mean([1.0 if r.get("ok") else 0.0 for r in all_stage_records]), 4),
    }
    speed = {
        "median_wall_seconds": round(median(latencies), 3),
        "p90_wall_seconds": round(percentile(latencies, 90), 3),
        "total_wall_seconds": round(sum(latencies), 1),
        "completion_tokens": completion_tokens,
        "tokens_per_second": round(completion_tokens / api_seconds, 1) if api_seconds else 0.0,
    }

    # Context sizing: per-call prompt and prompt+completion across every request,
    # so the high-water mark shows whether a smaller context window would suffice.
    call_prompts: list[float] = []
    call_totals: list[float] = []
    for record in all_stage_records:
        for prompt_tokens, completion in record.get("calls_usage", []):
            call_prompts.append(float(prompt_tokens))
            call_totals.append(float(prompt_tokens + completion))
        record.pop("calls_usage", None)  # keep persisted records lean
    context = {
        "max_prompt_tokens": int(max(call_prompts, default=0)),
        "max_total_tokens": int(max(call_totals, default=0)),
        "median_total_tokens": int(round(median(call_totals))) if call_totals else 0,
        "p90_total_tokens": int(round(percentile(call_totals, 90))) if call_totals else 0,
        "n_calls": len(call_totals),
    }

    return {
        "kind": "task",
        "model_key": model_key,
        "label": model_cfg.get("label", model_key),
        "arch": model_cfg.get("arch"),
        "quant": model_cfg.get("quant"),
        "vram_gb": model_cfg.get("vram_gb"),
        "server_context_tokens": model_cfg.get("server_context_tokens"),
        "endpoint": cfg["endpoint"],
        "served_model": model_cfg.get("model", "code"),
        "n_notes": len(notes),
        "grades": grades,
        "robustness": robustness,
        "speed": speed,
        "context": context,
        "per_note": per_note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate one served task model.")
    parser.add_argument("--model", required=True, help="model key from configs/task_models.yaml")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT))
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N notes")
    parser.add_argument("--embed-url", default="http://llms:8005",
                        help="embedding endpoint for summary cosine (set empty to skip)")
    parser.add_argument("--stages", default="",
                        help="comma-separated subset of stages to run for a fast pass, "
                             "e.g. property-values (domain-only). Default: all stages.")
    parser.add_argument("--tag", default="",
                        help="suffix the result file (task_<key>_<tag>.json) so a partial-stage "
                             "pass doesn't overwrite the full run.")
    args = parser.parse_args()

    stages = {s.strip() for s in args.stages.split(",") if s.strip()} or None
    result = run(
        args.model,
        vault_root=Path(args.vault_root),
        limit=args.limit,
        embed_url=args.embed_url or None,
        stages=stages,
    )
    suffix = f"_{args.tag}" if args.tag else ("_partial" if stages else "")
    out_path = RESULTS_DIR / f"task_{args.model}{suffix}.json"
    dump_json(out_path, result)

    g = result["grades"]
    print(f"\n== {result['label']} ==")
    if g.get("classify-type"):
        print(f"  type accuracy:        {g['classify-type']['accuracy']}")
    if g.get("property-values"):
        for field, gr in g["property-values"].items():
            print(f"  {field:<18} accuracy: {gr['accuracy']}")
    if g.get("assign-folder"):
        print(f"  folder accuracy:      {g['assign-folder']['accuracy']}")
    if g.get("classify-person"):
        print(f"  person-kind accuracy: {g['classify-person']['accuracy']}")
    if g.get("summary"):
        print(f"  summary cosine:       {g['summary'].get('mean_cosine')}  len_ok: {g['summary'].get('length_ok_rate')}")
    if g.get("refine-body"):
        print(f"  refine preservation:  {g['refine-body']['mean_preservation']}  added: {g['refine-body']['mean_added_ratio']}")
    print(f"  valid_rate: {result['robustness']['valid_rate']}  first_pass_json: {result['robustness']['first_pass_json_rate']}")
    print(f"  tokens/s: {result['speed']['tokens_per_second']}  median note-stage: {result['speed']['median_wall_seconds']}s")
    ctx = result["context"]
    window = result.get("server_context_tokens")
    window_note = f" / {window} window" if window else ""
    print(f"  context high-water: {ctx['max_total_tokens']} tok (prompt {ctx['max_prompt_tokens']} + gen){window_note}; "
          f"median {ctx['median_total_tokens']}, p90 {ctx['p90_total_tokens']}")
    if window and ctx["max_total_tokens"] > 0.9 * window:
        print(f"  WARNING: context high-water is within 10% of the {window}-token window — "
              f"outputs may have been truncated; consider a larger window.")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
