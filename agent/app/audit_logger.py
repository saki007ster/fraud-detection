"""
Structured audit logger — writes AgentEventLog records as JSONL.

In production: writes to ADLS Gen2 logs/ container via azure-storage-blob.
In local dev / testing: writes to a local file with fallback.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schemas import AgentEventLog

logger = logging.getLogger(__name__)


class AuditLogger:
    """Append-only JSONL writer for agent audit events."""

    def __init__(
        self,
        *,
        adls_connection_string: str | None = None,
        adls_container: str = "logs",
        local_path: str = "logs/audit_events.jsonl",
    ) -> None:
        self._adls_conn = adls_connection_string
        self._adls_container = adls_container
        self._local_path = local_path
        self._blob_client = None

        if self._adls_conn:
            try:
                from azure.storage.blob import BlobServiceClient

                self._blob_client = BlobServiceClient.from_connection_string(
                    self._adls_conn
                )
                logger.info("AuditLogger: using ADLS backend (container=%s)", adls_container)
            except Exception as exc:
                logger.warning("AuditLogger: ADLS init failed (%s), falling back to local file", exc)
        else:
            logger.info("AuditLogger: using local file backend (%s)", local_path)
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)

    def write_event(self, event: "AgentEventLog") -> str:
        """Serialize event to JSONL and append to storage.

        Returns the event_id for confirmation.
        """
        record = event.model_dump(mode="json")
        line = json.dumps(record, default=str) + "\n"

        if self._blob_client:
            self._write_adls(line, event.trace_id)
        else:
            self._write_local(line)

        logger.debug("Audit event written: %s (trace=%s)", event.event_id, event.trace_id)
        return event.event_id

    def _write_local(self, line: str) -> None:
        with open(self._local_path, "a") as f:
            f.write(line)

    def _write_adls(self, line: str, trace_id: str) -> None:
        """Append to a date-partitioned blob in ADLS.

        Blob path: logs/YYYY/MM/DD/audit_events.jsonl
        Uses AppendBlob for efficient appends.
        """
        now = datetime.now(timezone.utc)
        blob_path = f"{now:%Y/%m/%d}/audit_events.jsonl"

        try:
            container_client = self._blob_client.get_container_client(self._adls_container)
            blob_client = container_client.get_blob_client(blob_path)

            # Create append blob if it doesn't exist
            try:
                blob_client.get_blob_properties()
            except Exception:
                blob_client.create_append_blob()

            blob_client.append_block(line.encode("utf-8"))
        except Exception as exc:
            logger.error("ADLS write failed: %s — falling back to local", exc)
            self._write_local(line)
