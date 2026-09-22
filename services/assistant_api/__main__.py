"""Technical local CLI for historical jobs; never exposed through the assistant."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data_provider import DATA, NormalizedDataProvider
from .historical_runner import HistoricalForecastRunner
from .runner import LocalResearchProvider


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m services.assistant_api")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--data-dir", type=Path, help="Directory with normalized fendi-engine-series.csv")
    parser.add_argument("--research-dir", type=Path, help="Optional local YYYY-MM.json evidence snapshots")
    commands = parser.add_subparsers(dest="command", required=True)
    historical = commands.add_parser("historical")
    historical.add_argument("--start", required=True)
    historical.add_argument("--end", required=True)
    historical.add_argument("--force-rerun", action="store_true")
    historical.add_argument("--continue-on-error", action="store_true")
    month = commands.add_parser("month")
    month.add_argument("--period", required=True)
    month.add_argument("--force-rerun", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--resume-from")
    for name in ("status", "cancel", "pause"):
        sub = commands.add_parser(name)
        sub.add_argument("--run-id", required=True)
    args = parser.parse_args()
    runner = HistoricalForecastRunner(NormalizedDataProvider(data_dir=args.data_dir or DATA),
                                      research=LocalResearchProvider(args.research_dir),
                                      state_dir=args.state_dir)
    if args.command == "historical":
        result = runner.run_range(args.start, args.end, stop_on_error=not args.continue_on_error,
                                  force_rerun=args.force_rerun)
    elif args.command == "month":
        result = runner.run_month(args.period, force_rerun=args.force_rerun)
    elif args.command == "resume":
        result = runner.resume(args.run_id, resume_from=args.resume_from)
    elif args.command == "status":
        result = json.loads((runner.state_dir / "jobs" / f"{args.run_id}.json").read_text(encoding="utf-8"))
    elif args.command == "cancel":
        runner.cancel(args.run_id)
        result = {"run_id": args.run_id, "cancel_requested": True}
    else:
        runner.pause(args.run_id)
        result = {"run_id": args.run_id, "pause_requested": True}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
