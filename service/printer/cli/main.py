from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib import request

from printer.calibration import build_calibration_ruler
from printer.transport.escpos_file import FilePrinter


def cmd_calibrate(args: argparse.Namespace) -> int:
    img = build_calibration_ruler(target_height_px=args.height)
    if args.dump:
        img.save(args.dump)
        print(f"saved {args.dump}")
        return 0
    device = args.device or os.environ.get("PRINTER_DEVICE", "/dev/usb/lp0")
    p = FilePrinter(device)
    try:
        p.print_image(img, auto_cut=True, feed_lines_after=4)
    finally:
        p.close()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    import time

    import uvicorn

    from printer.app import AppDeps, create_app
    from printer.config import ServiceConfig
    from printer.health import HealthCollector
    from printer.paths import StatePaths
    from printer.queue.cache import PngCache
    from printer.queue.idempotency import IdempotencyCache
    from printer.queue.joblog import JobLog
    from printer.queue.worker import (
        PrintWorker,
        WorkerDeps,
        make_options_lookup,
        options_from_replay,
    )
    from printer.transport.runtime import FilePrinterAdapter
    from printer.transport.status import StatusReader

    cfg = ServiceConfig.from_env()
    paths = StatePaths(cfg.state_dir)
    paths.ensure()
    log = JobLog(paths.joblog_path)
    # Compact on startup so long-running deployments don't grow the log
    # forever. Pruning drops oldest terminal-job records first; pending
    # jobs (replayed by the worker below) are always preserved.
    log.prune(max_records=cfg.json_log_max_jobs,
              max_bytes=cfg.json_log_max_bytes)
    idem = IdempotencyCache(paths.idempotency_path, ttl_s=cfg.idempotency_ttl_s)
    cache = PngCache(paths.cache, max_bytes=cfg.png_cache_max_bytes,
                     ttl_s=cfg.png_cache_ttl_s)
    transport = FilePrinterAdapter(cfg.device)
    # Rebuild per-job options from the durable log so jobs accepted before
    # a crash/restart retain their ``auto_cut``/``feed_lines_after``/
    # ``expires_at``. Without this, the worker would fall back to the
    # ``(True, 2, None)`` default and could print expired jobs.
    options_store: dict = options_from_replay(log)

    started_at = time.time()

    def _last_print_at() -> str | None:
        # Lazy: scan the durable log for the most recent ``printed`` event.
        # Same pattern as /metrics paper_total. Cheap because the log is small
        # (capped to json_log_max_jobs) and only invoked on /healthz.
        latest: str | None = None
        for r in log.replay():
            if r.event == "printed":
                latest = r.ts
        return latest

    def _last_error() -> str | None:
        latest: str | None = None
        for r in log.replay():
            if r.event in {"retry", "expired", "retry_timeout", "unknown_partial"}:
                latest = r.detail or r.event
        return latest

    def _oldest_pending_age_s() -> int | None:
        pending = log.pending_after_replay()
        if not pending:
            return None
        ts = pending[0].ts
        try:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            accepted_at = datetime.fromisoformat(ts)
            if accepted_at.tzinfo is None:
                accepted_at = accepted_at.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None
        return max(0, int(time.time() - accepted_at.timestamp()))

    health = HealthCollector(
        status_reader=StatusReader(supports_status=False),
        queue_depth=lambda: len(log.pending_after_replay()),
        last_print_at=_last_print_at,
        last_error=_last_error,
        oldest_pending_age_s=_oldest_pending_age_s,
        process_started_at=started_at,
        clock_now=lambda: time.time(),
    )
    worker = PrintWorker(
        WorkerDeps(joblog=log, png_cache=cache, transport=transport,
                   retry_interval_s=cfg.retry_interval_s,
                   max_retry_age_s=cfg.max_retry_age_s,
                   # Spec §11: suspend expiry checks while the Pi clock is
                   # unsynchronized. ``snapshot()`` shells out to
                   # ``timedatectl`` lazily at expiry-check time.
                   clock_ok=lambda: health.snapshot().clock_synchronized),
        options_lookup=make_options_lookup(options_store),
    )
    deps = AppDeps(config=cfg, paths=paths, joblog=log, idem=idem,
                   png_cache=cache, worker=worker, transport=transport,
                   health=health, options_store=options_store)
    app = create_app(deps)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    return 0


def cmd_test_print(args: argparse.Namespace) -> int:
    url = (args.url or os.environ.get("PRINTER_SERVICE_URL") or
           f"http://{os.environ.get('PRINTER_HOST', '127.0.0.1')}:"
           f"{os.environ.get('PRINTER_PORT', '8000')}")
    url = url.rstrip("/") + "/test"
    req = request.Request(url, method="POST")
    try:
        with request.urlopen(req, timeout=args.timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(body)
                body = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
            print(f"{resp.status} {url}")
            if body:
                print(body)
        return 0
    except OSError as exc:
        print(f"printer-svc test-print failed: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="printer-svc")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calibrate", help="print the DPI calibration ruler")
    c.add_argument("--height", type=int, default=2000)
    c.add_argument("--device", default=None)
    c.add_argument("--dump", type=Path, default=None,
                   help="dump PNG to file instead of printing")
    c.set_defaults(func=cmd_calibrate)

    r = sub.add_parser("run", help="run the FastAPI service")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("test-print", help="POST the bundled test page")
    t.add_argument("--url", default=None,
                   help="service base URL (default: PRINTER_SERVICE_URL or host/port env)")
    t.add_argument("--timeout", type=float, default=30.0)
    t.set_defaults(func=cmd_test_print)

    ns = p.parse_args(argv)
    return ns.func(ns)
