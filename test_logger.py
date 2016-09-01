import logging
import os
import sys

# Initialize logger
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("musicbot")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "%(asctime)s (%(levelname)s, %(filename)s:%(lineno)s): %(message)s", datefmt="%H:%M:%S")

file_handler = logging.FileHandler("logs/tests.log", encoding="utf-8", mode='w')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

info_handler = logging.StreamHandler(sys.stdout)
info_handler.setLevel(logging.INFO)
info_filter = logging.Filter()
info_filter.filter = lambda record: record.levelno == logging.INFO
info_handler.addFilter(info_filter)
info_handler.setFormatter(formatter)
logger.addHandler(info_handler)

error_handler = logging.StreamHandler(sys.stderr)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)
logger.addHandler(error_handler)
