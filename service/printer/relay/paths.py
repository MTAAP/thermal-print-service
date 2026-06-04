from __future__ import annotations

from pathlib import Path


class RelayPaths:
    """Layout of /var/lib/printer/relay/. Mirrors printer.paths.StatePaths so
    the deploy provisioning (0750 thermalprinter:thermalprinter) is uniform."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def creds_path(self) -> Path:
        return self.root / "creds.json"

    @property
    def allowlist_path(self) -> Path:
        return self.root / "allowlist.json"

    @property
    def invites_path(self) -> Path:
        return self.root / "invites.json"

    @property
    def jobmap_path(self) -> Path:
        # Append-only JSONL: each line is a hub_job_id -> {local_job_id,
        # last_status} update. The last line for a job id wins on replay.
        return self.root / "jobmap.jsonl"
