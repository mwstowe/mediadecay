"""Daily maintenance job — sync, evaluate, delete, notify."""

import argparse
import logging
import sys

from mediadecay.config import load_config, get_config
from mediadecay.db import init_db
from mediadecay.engine import EngineReport, run_maintenance_cycle
from mediadecay import notify

log = logging.getLogger("mediadecay")


def _format_report(report: EngineReport, dry_run: bool) -> str:
    lines = []
    mode = "DRY RUN" if dry_run else "LIVE"
    lines.append(f"=== MediaDecay Maintenance [{mode}] ===\n")

    deletions = [r for r in report.results if r.action == "delete"]
    if deletions:
        lines.append(f"Deletions ({len(deletions)}):")
        for r in deletions:
            lines.append(f"  - {r.title} [{r.manager}] — {r.reason}")
    else:
        lines.append("No deletions.")

    if report.orphans:
        lines.append(f"\nOrphans detected ({len(report.orphans)}):")
        for r in report.orphans:
            lines.append(f"  - {r.title}")

    if report.errors:
        lines.append(f"\nErrors ({len(report.errors)}):")
        for e in report.errors:
            lines.append(f"  - {e}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MediaDecay maintenance job")
    parser.add_argument("--dry-run", action="store_true", default=None)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    load_config(args.config)
    cfg = get_config()
    init_db()

    # Configure logging
    log_file = cfg.get("maintenance", {}).get("log_file")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            *([] if not log_file else [logging.FileHandler(log_file)]),
        ],
    )

    dry_run = args.dry_run if args.dry_run is not None else cfg.get("maintenance", {}).get("dry_run", True)

    log.info("Starting maintenance run (dry_run=%s)", dry_run)

    from mediadecay.engine import maintenance_guard
    with maintenance_guard() as acquired:
        if not acquired:
            log.error("Another maintenance run is already in progress "
                      "(service or CLI). Aborting to avoid concurrent destructive runs.")
            sys.exit(1)

        # Run the single shared maintenance sequence (same path as the
        # scheduler and web UI). scan_orphans=True so the CLI report can list
        # orphaned media, matching its historical behavior.
        try:
            outcome = run_maintenance_cycle(dry_run=dry_run, scan_orphans=True)
        except Exception as e:
            log.error(f"Maintenance run failed: {e}")
            sys.exit(1)
        report = outcome.report

        # Report
        summary = _format_report(report, dry_run)
        log.info(summary)

        # Notify
        notify.send("MediaDecay Report", summary)

        # Checkpoint WAL to ensure all data is flushed to main DB
        try:
            from mediadecay.db import checkpoint
            checkpoint()
        except Exception as e:
            log.warning(f"WAL checkpoint failed: {e}")

    log.info("Maintenance complete.")


if __name__ == "__main__":
    main()
