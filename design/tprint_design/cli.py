"""tprint-design entry point.

Subcommands are wired in via ``_build_parser``. Each subcommand
implementation lives in its own private function (``_cmd_<name>``) and
returns an exit code: 0 = success, 1 = lint errors, 2 = render/IO error.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from printer_core.constants import (
    DPMM,
    LIVE_WIDTH_PX,
    PRINT_HEAD_WIDTH_PX,
)

from tprint_design.pi_info import effective_max_length_mm

if TYPE_CHECKING:
    import httpx


def _load_guidelines_md() -> str:
    return (files("tprint_design") / "guidelines.md").read_text()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tprint-design")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_info = sub.add_parser("info", help="Show engine + design info")
    p_info.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON")

    p_init = sub.add_parser("init", help="Drop a starter HTML scaffold")
    p_init.add_argument("path", type=Path, help="Destination .html file")
    p_init.add_argument("--template", choices=[
        "banner", "blank", "literary", "note", "scroll",
    ], default="blank")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing file")

    p_compile = sub.add_parser("compile", help="Render HTML to thermal PNG")
    p_compile.add_argument("path", type=Path, help="Source .html file")
    p_compile.add_argument("--out", type=Path, default=None,
                           help="Override output PNG path")
    p_compile.add_argument("--no-lint", action="store_true",
                           help="Skip lint pass; exit 0 on render success")
    p_compile.add_argument("--max-length-mm", type=int, default=None,
                           help="Override Pi max_length_mm for lint")
    p_compile.add_argument("--width", type=int, default=576)

    p_lint = sub.add_parser("lint", help="Pre-render lint only (fast)")
    p_lint.add_argument("path", type=Path)
    p_lint.add_argument("--out", type=Path, default=None,
                        help="Write lint JSON to this path")

    p_print = sub.add_parser("print", help="Compile and send to the Pi")
    p_print.add_argument("path", type=Path)
    p_print.add_argument("--idempotency-key", default=None,
                         help="Stable key; defaults to sha256(png)[:16] so "
                              "re-running the same print is naturally idempotent")
    p_print.add_argument("--dry-run", action="store_true",
                         help="Validate at the Pi without printing")
    p_print.add_argument("--max-length-mm", type=int, default=None)
    p_print.add_argument("--allow-public-url", action="store_true",
                         help="Permit PRINT_SERVICE_URL hosts outside "
                              "tailnet/RFC1918/localhost (also via env "
                              "PRINT_SERVICE_ALLOW_PUBLIC_URL=1)")
    p_print.add_argument("--wait", action="store_true",
                         help="Poll /jobs/{id} until terminal state and "
                              "report the outcome before exiting")

    p_send = sub.add_parser(
        "send",
        help="Post an already-compiled PNG to the Pi (no recompile)",
    )
    p_send.add_argument("png", type=Path,
                        help="Path to a 576-px-wide 1-bit PNG")
    p_send.add_argument("--idempotency-key", default=None,
                        help="Stable key; defaults to sha256(png)[:16]")
    p_send.add_argument("--dry-run", action="store_true",
                        help="Validate at the Pi without printing")
    p_send.add_argument("--allow-public-url", action="store_true")
    p_send.add_argument("--wait", action="store_true",
                        help="Poll /jobs/{id} until terminal state")

    p_status = sub.add_parser(
        "status",
        help="Fetch the current state of a previously accepted job",
    )
    p_status.add_argument("job_id")
    p_status.add_argument("--wait", action="store_true",
                          help="Block until terminal state instead of "
                               "returning the snapshot")

    p_preview = sub.add_parser("preview", help="Compile + open in OS viewer")
    p_preview.add_argument("path", type=Path)

    return p


def _cmd_info(args: argparse.Namespace) -> int:
    md = _load_guidelines_md()
    if args.json:
        # Resolve via the same helper lint uses, so `info` and `lint` always
        # report the same effective cap. Today this returns the bundled
        # default; once a Pi-info refresh path lands, both surfaces will
        # pick up the cached value automatically.
        max_length_mm = effective_max_length_mm(flag_value=None)
        payload = {
            "live_width_px": LIVE_WIDTH_PX,
            "print_head_px": PRINT_HEAD_WIDTH_PX,
            "dpmm": DPMM,
            "max_length_mm_default": max_length_mm,
            "fonts_available": [
                "IBM Plex Sans", "JetBrains Mono", "Noto Sans SC",
            ],
            "starter_templates": ["banner", "blank", "literary", "note", "scroll"],
            "rules_markdown": md,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(md)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    if args.path.exists() and not args.force:
        print(f"refusing to overwrite {args.path} (use --force)", file=sys.stderr)
        return 2
    src = files("tprint_design.templates") / f"{args.template}.html"
    args.path.write_text(src.read_text())
    print(f"wrote {args.path} (template: {args.template})")
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    from PIL import Image

    from tprint_design.compile import compile_html
    from tprint_design.lint import lint_html_text

    try:
        result = compile_html(args.path, out_path=args.out, width=args.width)
    except Exception as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 2

    if args.no_lint:
        print(f"compiled {result.out_path} ({result.rendered_height_px} px)")
        return 0

    rgb = Image.open(result.rgb_path)
    one_bit = Image.open(result.out_path)
    rpt = lint_html_text(
        args.path.read_text(),
        source_path=args.path,
        rendered_rgb=rgb, rendered_one_bit=one_bit,
        render_ms=result.render_ms,
        blocked_external_requests=result.blocked_external_requests,
        max_length_mm_flag=args.max_length_mm,
    )
    lint_path = result.out_path.with_suffix(".lint.json")
    lint_path.write_text(json.dumps(rpt.to_dict(), indent=2))

    _print_lint_summary(rpt, result)
    return 0 if rpt.ok else 1


def _print_lint_summary(rpt, result) -> None:
    print(f"compiled {result.out_path} "
          f"({result.rendered_height_px} px, "
          f"~{result.estimated_paper_mm:.0f} mm of paper, "
          f"ink ratio {result.ink_pixel_ratio:.0%})")
    for f in rpt.errors:
        print(f"  ERROR  [{f.rule}] {f.message}")
    for w in rpt.warnings:
        print(f"  warn   [{w.rule}] {w.message}")


def _cmd_lint(args: argparse.Namespace) -> int:
    from tprint_design.lint import lint_html_file

    rpt = lint_html_file(args.path)
    if args.out:
        args.out.write_text(json.dumps(rpt.to_dict(), indent=2))
    for f in rpt.errors:
        print(f"  ERROR  [{f.rule}] {f.message}")
    for w in rpt.warnings:
        print(f"  warn   [{w.rule}] {w.message}")
    return 0 if rpt.ok else 1


def _http_client(url: str) -> httpx.Client:
    import httpx
    return httpx.Client(base_url=url, timeout=10.0)


def validate_print_service_url(url: str, *, allow_public: bool) -> str | None:
    """Returns None if the URL is acceptable, else a user-facing error.

    The print pipeline POSTs raw PNGs (which may carry intentionally
    sensitive content) to whatever host PRINT_SERVICE_URL points at.
    Prompt-injection or a misconfigured shell can flip that pointer to
    an arbitrary public host, so default-deny anything that isn't on the
    tailnet (*.ts.net), localhost, an RFC1918 IP, or a link-local IP.
    Operators can opt out via --allow-public-url or
    PRINT_SERVICE_ALLOW_PUBLIC_URL=1.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return (
            f"PRINT_SERVICE_URL scheme must be http or https, got "
            f"{parsed.scheme!r}"
        )
    host = parsed.hostname
    if not host:
        return "PRINT_SERVICE_URL has no host"
    if allow_public:
        return None
    if host in ("localhost", "127.0.0.1", "::1"):
        return None
    if host.endswith(".ts.net"):
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return (
            f"PRINT_SERVICE_URL host {host!r} is not on the tailnet "
            f"(*.ts.net), localhost, or an RFC1918 address. Pass "
            f"--allow-public-url (or set PRINT_SERVICE_ALLOW_PUBLIC_URL=1) "
            f"to override."
        )
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return None
    return (
        f"PRINT_SERVICE_URL host {host} is a public IP. Pass "
        f"--allow-public-url (or set PRINT_SERVICE_ALLOW_PUBLIC_URL=1) "
        f"to override."
    )


def _resolve_base_url(args: argparse.Namespace) -> tuple[str | None, int]:
    """Read + validate PRINT_SERVICE_URL. Returns (url, exit_code).

    On success returns ``(url, 0)``; on failure returns ``(None, 2)``
    and has already printed the user-facing error to stderr.
    """
    import os

    base_url = os.environ.get("PRINT_SERVICE_URL")
    if not base_url:
        print("PRINT_SERVICE_URL is unset", file=sys.stderr)
        return None, 2
    allow_public = getattr(args, "allow_public_url", False) or os.environ.get(
        "PRINT_SERVICE_ALLOW_PUBLIC_URL", ""
    ).lower() in ("1", "true", "yes")
    err = validate_print_service_url(base_url, allow_public=allow_public)
    if err is not None:
        print(err, file=sys.stderr)
        return None, 2
    return base_url, 0


def _post_with_retry_and_handle(
    base_url: str, png_bytes: bytes, *,
    idempotency_key: str | None, dry_run: bool,
) -> tuple[dict | None, int]:
    """POST the PNG with retry; return (response, exit_code).

    Centralizes the error-handling shape so ``print`` and ``send`` share
    identical user-visible behavior on success, structured rejection,
    and transport failure.
    """
    import httpx

    from tprint_design.client import (
        PrintClientError,
        derive_idempotency_key,
        post_print_raw_with_retry,
    )

    if idempotency_key is None:
        idempotency_key = derive_idempotency_key(png_bytes)

    with _http_client(base_url) as client:
        try:
            response = post_print_raw_with_retry(
                client, png_bytes,
                idempotency_key=idempotency_key,
                dry_run=dry_run,
            )
        except PrintClientError as exc:
            print(f"pi rejected the print: {exc}", file=sys.stderr)
            return None, 2
        except httpx.HTTPError as exc:
            # Connect refused, DNS failure, timeout, mid-stream RST — all
            # surface as httpx.HTTPError subclasses. Without this catch they
            # bubble as a Python stack trace, which is the worst possible UX
            # for the primary failure mode (Pi unreachable / Tailscale slow).
            print(f"network error reaching Pi: {exc}", file=sys.stderr)
            return None, 2
    return response, 0


def _cmd_print(args: argparse.Namespace) -> int:
    from PIL import Image

    from tprint_design.compile import compile_html
    from tprint_design.lint import lint_html_text

    base_url, rc = _resolve_base_url(args)
    if base_url is None:
        return rc

    try:
        result = compile_html(args.path)
    except Exception as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 2

    rgb = Image.open(result.rgb_path)
    one_bit = Image.open(result.out_path)
    rpt = lint_html_text(
        args.path.read_text(),
        source_path=args.path,
        rendered_rgb=rgb, rendered_one_bit=one_bit,
        render_ms=result.render_ms,
        blocked_external_requests=result.blocked_external_requests,
        max_length_mm_flag=args.max_length_mm,
    )
    if not rpt.ok:
        for f in rpt.errors:
            print(f"  ERROR  [{f.rule}] {f.message}", file=sys.stderr)
        print("refusing to print: lint errors above", file=sys.stderr)
        return 1

    png_bytes = result.out_path.read_bytes()
    response, rc = _post_with_retry_and_handle(
        base_url, png_bytes,
        idempotency_key=args.idempotency_key,
        dry_run=args.dry_run,
    )
    if response is None:
        return rc
    print(json.dumps(response, indent=2))
    if getattr(args, "wait", False) and not args.dry_run and "id" in response:
        return _wait_and_print_status(base_url, response["id"])
    return 0


def _cmd_send(args: argparse.Namespace) -> int:
    """Post an already-compiled PNG without recompiling.

    Useful for the workflow ``compile`` → ``Read png`` → iterate →
    finally send: the print path's ~1 s browser-spawn cost is paid
    once during compile, then avoided on subsequent sends of the same
    PNG. Validates the PNG width before posting because the Pi rejects
    non-576-px-wide images with a 400 (slower round-trip than catching
    it locally).
    """
    from PIL import Image

    base_url, rc = _resolve_base_url(args)
    if base_url is None:
        return rc

    if not args.png.exists():
        print(f"png not found: {args.png}", file=sys.stderr)
        return 2
    png_bytes = args.png.read_bytes()
    try:
        with Image.open(args.png) as img:
            if img.width != PRINT_HEAD_WIDTH_PX:
                print(
                    f"png is {img.width}px wide; must be exactly "
                    f"{PRINT_HEAD_WIDTH_PX}px",
                    file=sys.stderr,
                )
                return 2
    except Exception as exc:
        print(f"png decode error: {exc}", file=sys.stderr)
        return 2

    response, rc = _post_with_retry_and_handle(
        base_url, png_bytes,
        idempotency_key=args.idempotency_key,
        dry_run=args.dry_run,
    )
    if response is None:
        return rc
    print(json.dumps(response, indent=2))
    if getattr(args, "wait", False) and not args.dry_run and "id" in response:
        return _wait_and_print_status(base_url, response["id"])
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Fetch the current state of a previously accepted job."""
    base_url, rc = _resolve_base_url(args)
    if base_url is None:
        return rc
    if args.wait:
        return _wait_and_print_status(base_url, args.job_id)
    return _print_status_snapshot(base_url, args.job_id)


_TERMINAL_STATES = ("printed", "expired", "retry_timeout", "unknown_partial")


def _fetch_job(base_url: str, job_id: str) -> dict | None:
    import httpx

    with _http_client(base_url) as client:
        try:
            r = client.get(f"/jobs/{job_id}")
        except httpx.HTTPError as exc:
            print(f"network error reaching Pi: {exc}", file=sys.stderr)
            return None
    if r.status_code == 404:
        print(f"job not found: {job_id}", file=sys.stderr)
        return None
    if not r.is_success:
        print(f"pi returned {r.status_code}: {r.text}", file=sys.stderr)
        return None
    return r.json()


def _print_status_snapshot(base_url: str, job_id: str) -> int:
    job = _fetch_job(base_url, job_id)
    if job is None:
        return 2
    print(json.dumps(job, indent=2))
    return 0


def _wait_and_print_status(
    base_url: str, job_id: str, *,
    poll_interval_s: float = 2.0,
    timeout_s: float = 120.0,
) -> int:
    import time

    deadline = time.monotonic() + timeout_s
    last_job: dict | None = None
    while time.monotonic() < deadline:
        job = _fetch_job(base_url, job_id)
        if job is None:
            return 2
        last_job = job
        if job.get("status") in _TERMINAL_STATES:
            print(json.dumps(job, indent=2))
            return 0 if job["status"] == "printed" else 1
        time.sleep(poll_interval_s)
    print(
        f"timed out after {timeout_s:.0f}s waiting for terminal state; "
        f"last status: {last_job and last_job.get('status')!r}",
        file=sys.stderr,
    )
    return 2


def _open_default(path: Path) -> None:
    import platform
    import subprocess
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", str(path)], check=False)
    elif system == "Linux":
        subprocess.run(["xdg-open", str(path)], check=False)
    elif system == "Windows":
        subprocess.run(["explorer", str(path)], check=False)


def _cmd_preview(args: argparse.Namespace) -> int:
    from tprint_design.compile import compile_html
    try:
        result = compile_html(args.path)
    except Exception as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 2
    _open_default(result.out_path)
    return 0


_DISPATCH = {
    "info": _cmd_info, "init": _cmd_init,
    "compile": _cmd_compile, "lint": _cmd_lint,
    "print": _cmd_print, "send": _cmd_send,
    "status": _cmd_status, "preview": _cmd_preview,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _DISPATCH[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
