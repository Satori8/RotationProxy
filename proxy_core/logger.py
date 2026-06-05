import logging


class ColoredFormatter(logging.Formatter):
    GREY = "\x1b[90m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record):
        import copy

        rec = copy.copy(record)
        color = self.COLORS.get(rec.levelno, self.RESET)
        rec.levelname = f"{color}{rec.levelname}{self.RESET}"
        rec.msg = f"{color}{rec.msg}{self.RESET}"
        return super().format(rec)


# Configure loggers
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

import os
import sys

process_type = os.environ.get("GEMINI_PROXY_PROCESS", "server")
log_file = "proxy_gui.log" if process_type == "gui" else "proxy_server.log"

# Add file handler to root logger
try:
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    file_handler.setLevel(logging.INFO)
    logging.root.addHandler(file_handler)
except Exception as e:
    # Fallback to sys.stderr if file cannot be opened
    print(f"Failed to open log file {log_file}: {e}", file=sys.stderr)

# Apply ColoredFormatter to console stream handlers
for handler in logging.root.handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.setFormatter(
            ColoredFormatter("%(asctime)s [%(levelname)s] %(message)s")
        )

# Suppress verbose third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger("proxy")
