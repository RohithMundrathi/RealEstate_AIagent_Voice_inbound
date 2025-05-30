import logging
import sys
from logging.handlers import RotatingFileHandler
from app.config import Config

def setup_logging(app):
    log_level = getattr(logging, Config.LOG_LEVEL.upper())
    log_format = logging.Formatter(Config.LOG_FORMAT)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    if not Config.TESTING:
        file_handler = RotatingFileHandler(
            "app.log", maxBytes=10485760, backupCount=5
        )
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)

    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    app.logger.setLevel(log_level)
    return app
