
from datetime import datetime
import json
import logging
import os


def save_secrets():
    with open("config/secrets.json", 'r') as secrets_file:
        secrets = json.loads(secrets_file.read())
        secrets_keys = secrets.keys()

    print("Reading secrets from environment variables")
    secrets = {}

    missing_key = False
    for key in secrets_keys:
        try:
            secrets[key] = os.environ[key]
        except KeyError:
            print("Missing key:", key)
            missing_key = True

    if missing_key:
        print("Aborting...")
        return

    print("Writing secrets to secrets.json")
    with open("config/secrets.json", 'w') as secrets_file:
        secrets_file.write(json.dumps(secrets))


def initialize_logger():
    print("Initializing logger")

    # Initialize logger
    os.makedirs("logs", exist_ok=True)

    logger = logging.getLogger("musicbot")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s (%(levelname)s, %(filename)s:%(lineno)s): %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(datetime.utcnow().strftime("logs/tests.log"), encoding="utf-8", mode='w')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


if __name__ == '__main__':
    save_secrets()
    initialize_logger()
