from __future__ import annotations

import logging
import re
import secrets
import string
from pathlib import Path

from rich.logging import RichHandler

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-zA-Z0-9-]{1,63}\.)+[A-Za-z]{2,63}$"
)


def setup_logging(write_file: bool = False, log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("fm")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.addHandler(RichHandler(rich_tracebacks=True, show_path=False))
    if write_file and log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    return logger


def validate_domain(domain: str) -> bool:
    return bool(DOMAIN_RE.match(domain))


def generate_secure_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))
