import logging
import os

import jwt

secrets_keys = [
    'gmusic_username',
    'gmusic_password',
    'gmusic_device_id',
    'youtube_api_key',
    'soundcloud_id',
    'telegram_gmusic_bot_token',
    'telegram_youtube_bot_token',
    'telegram_soundcloud_bot_token'
]


def save_secrets():
    logger = logging.getLogger("musicbot")
    logger.info("Reading secrets from environment variables")
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

    logger.info("Writing secrets to secrets.json")
    with open("config/secrets.dat", 'wb') as secrets_file:
        secrets_file.write(jwt.encode(secrets, "testpw", algorithm="HS256"))


if __name__ == '__main__':
    save_secrets()
