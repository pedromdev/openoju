from __future__ import annotations

import logging
import signal
import threading

from .config import get_settings
from .db import SessionLocal
from .services.retention import run_retention

logger = logging.getLogger("openoju.maintenance")
_stop = threading.Event()


def _signal_handler(signum, _frame) -> None:  # type: ignore[no-untyped-def]
    logger.info("sinal %s recebido; encerrando", signum)
    _stop.set()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    logger.info("maintenance iniciado")
    while not _stop.is_set():
        db = SessionLocal()
        try:
            counts = run_retention(db, settings)
            logger.info("retenção: %s", counts)
        except Exception as exc:  # noqa: BLE001 - maintenance must stay alive
            logger.exception("erro na retenção: %s", exc)
            db.rollback()
        finally:
            db.close()
        _stop.wait(settings.maintenance_interval_s)
    logger.info("maintenance encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
