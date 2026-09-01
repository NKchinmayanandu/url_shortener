import logging
import sys
import os
from logging.handlers import RotatingFileHandler

def setup_logging(level: str = "INFO") -> None:
    os.makedirs("logs", exist_ok=True)
    rotating_handler = RotatingFileHandler(
        "logs/platform.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,  
        encoding="utf-8"
    )
    
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            rotating_handler
        ]
    )
    
    # Mute noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
