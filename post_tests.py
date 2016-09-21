import os
import shutil

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


def restore_blank_secrets():
    print("Removing secrets")
    os.remove("config/secrets.dat")


def save_logs():
    print("Copying logs to artifacts dir")

    tests_logs_path = "logs/tests.log"
    target_dir = os.environ['CIRCLE_ARTIFACTS']
    shutil.copy(tests_logs_path, target_dir)


if __name__ == '__main__':
    restore_blank_secrets()
    save_logs()
