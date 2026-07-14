"""Smoke-test public compliance endpoints and admin protection."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app


def main() -> None:
    with TestClient(app) as client:
        for path in (
            "/health",
            "/review-metrics",
            "/history/metrics",
            "/procurement-rules",
            "/alerts.rss",
        ):
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code, response.text)
        protected = client.post("/admin/anomalies/detect")
        assert protected.status_code == 403
    print("PASS: public compliance endpoints respond and admin mutation is protected")


if __name__ == "__main__":
    main()
