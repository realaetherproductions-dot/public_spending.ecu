from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from services.alert_dispatch_service import dispatch_confirmed_alerts


def main() -> None:
    init_db()
    with SessionLocal() as db:
        print(dispatch_confirmed_alerts(db))


if __name__ == "__main__":
    main()
