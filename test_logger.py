import logging
import os

# Initialize logger
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "%(asctime)s (%(levelname)s, %(filename)s:%(lineno)s): %(message)s", datefmt="%H:%M:%S")

file_handler = logging.FileHandler("logs/tests.log", encoding="utf-8", mode='w')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
