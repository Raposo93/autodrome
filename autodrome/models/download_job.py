from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4


TERMINAL_STATUSES = {"succeeded", "failed", "interrupted"}
RETRYABLE_STATUSES = {"failed", "interrupted"}
JOB_STATUSES = {"queued", "running"} | TERMINAL_STATUSES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DownloadJob:
    job_id: str
    payload: Dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    error: Optional[str] = None
    retry_of: Optional[str] = None

    @classmethod
    def create(cls, payload: Dict[str, Any]) -> "DownloadJob":
        timestamp = utc_now()
        return cls(
            job_id=str(uuid4()),
            payload=dict(payload),
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DownloadJob":
        status = data.get("status")
        if status not in JOB_STATUSES:
            raise ValueError(f"Invalid persisted job status: {status}")

        return cls(
            job_id=data["job_id"],
            payload=dict(data["payload"]),
            status=status,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            error=data.get("error"),
            retry_of=data.get("retry_of"),
        )

    def transition(self, status: str, error: Optional[str] = None) -> None:
        if status not in JOB_STATUSES:
            raise ValueError(f"Invalid job status: {status}")
        self.status = status
        self.error = error
        self.updated_at = utc_now()

    def to_storage_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "payload": self.payload,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "retry_of": self.retry_of,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            **self.payload,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "retry_of": self.retry_of,
        }
