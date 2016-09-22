import base64
import json
import locale
import logging
import os
from getpass import getpass
from os import path

import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import _version

_config_dir = "config"


def _load_config():
    config_path = path.join(_config_dir, "config.json")
    with open(config_path, 'r') as config_file:
        return json.loads(config_file.read())


def _save_config():
    config_path = path.join(_config_dir, "config.json")
    with open(config_path, 'w') as config_file:
        return config_file.write(json.dumps(_config))


_config = _load_config()


def get_secrets_dir():
    return path.expanduser(_config.get("secrets_location", "config"))


def _get_secrets_path():
    return path.join(get_secrets_dir(), "secrets.dat")


if _version.debug:
    _secrets_password = "testpw"
else:
    _confirmed = False
    _secrets_password = None
    while not _confirmed:
        _secrets_password = getpass("Enter secrets password: ")
        if not path.isfile(_get_secrets_path()):
            # Reconfirm password if it's new
            _confirm_password = getpass("Reconfirm secrets password: ")
            if _secrets_password != _confirm_password:
                print("Passwords don't match, please try again.")
                continue
        _confirmed = True

salt_path = path.join(get_secrets_dir(), "salt.txt")

if path.isfile(salt_path):
    with open(salt_path, 'rb') as salt_file:
        salt = salt_file.read()
else:
    salt = os.urandom(16)
    with open(salt_path, 'wb') as salt_file:
        salt_file.write(salt)

kdf = PBKDF2HMAC(
    algorithm=hashes.SHA256(),
    length=32,
    salt=salt,
    iterations=100000,
    backend=default_backend()
)
key = base64.urlsafe_b64encode(kdf.derive(_secrets_password.encode()))


def _load_jwt_secrets():
    """
    Loads secrets from the secrets.dat if they are JWT data.
    This is a legacy method and will be removed in November 2016.
    :return: the secrets or None
    """
    secrets_path = _get_secrets_path()
    if not path.isfile(secrets_path):
        logging.getLogger("musicbot").debug("No jwt secrets file found")
        return None
    with open(secrets_path, 'rb') as secrets_file:
        try:
            return jwt.decode(secrets_file.read(), _secrets_password, algorithm="HS256")
        except jwt.exceptions.InvalidTokenError:
            return None


def _load_json_secrets():
    """
    Loads secrets from unencrypted secrets.json.
    This is a legacy method and will be removed in November 2016.
    :return: the secrets or None
    """
    logger = logging.getLogger("musicbot")
    secrets_path = path.join(get_secrets_dir(), "secrets.json")
    if not path.isfile(secrets_path):
        logger.debug("No json secrets file found")
        return None
    with open(secrets_path, 'r') as secrets_file:
        secrets = json.loads(secrets_file.read())
    for secrets_key in ["gmusic_bot_token", "youtube_bot_token", "soundcloud_bot_token"]:
        if secrets_key in secrets:
            token = secrets[secrets_key]
            del secrets[secrets_key]
            secrets["telegram_" + secrets_key] = token
    logger.info("You can remove the secrets.json now.")
    return secrets


def _load_secrets():
    jwt_secrets = _load_jwt_secrets()
    if jwt_secrets:
        return jwt_secrets

    secrets_path = _get_secrets_path()
    if not path.isfile(secrets_path):
        logging.getLogger("musicbot").debug("No secrets file found")
        json_secrets = _load_json_secrets()
        if json_secrets:
            return json_secrets
        return {}
    f = Fernet(key)
    with open(secrets_path, 'rb') as secrets_file:
        return json.loads(f.decrypt(secrets_file.read()).decode())


_secrets = _load_secrets()


def get_auto_updates_enabled():
    return _config.get("auto_updates", False)


def get_load_plugins_enabled():
    return _config.get("load_plugins", True)


def get_suggest_songs_enabled():
    return _config.get("suggest_songs", True)


def get_telegram_password_enabled():
    return _config.get("enable_session_password", False)


def set_telegram_password_enabled(enabled):
    _config["enable_session_password"] = enabled
    _save_config()


def get_allow_rest_admin():
    return _config.get("allow_rest_admin", True)


def get_gmusic_locale():
    return _config.get("gmusic_locale", locale.getdefaultlocale()[0])


def get_max_conversions():
    return _config.get("max_conversions", 2)


def get_max_downloads():
    return _config.get("max_downloads", 2)


def get_gmusic_quality():
    return _config.get("quality", "hi")


def set_gmusic_quality(quality):
    _config['quality'] = quality


def get_songs_path():
    return _config.get("song_path", "songs")


def get_secrets():
    """
    Get the secrets file content.
    If you change a value, call save_secrets() afterwards.
    :return: a JSON dict object containing the secrets
    """
    return _secrets


def save_secrets():
    """
    Save secrets to encrypted file on disk.
    """
    secrets_path = _get_secrets_path()
    f = Fernet(key)
    with open(secrets_path, 'wb') as secrets_file:
        secrets_file.write(f.encrypt(json.dumps(_secrets).encode()))


def request_secret(secret_key, message, hidden=True):
    """
    Request a secret from the user. Save the secrets to disk afterwards.
    If there is already a secret for the key, return it.
    :param secret_key: the key the input should be stored under in the secrets
    :param message: the message to show to the user
    :param hidden: hide the input (recommended for passwords and such)
    :return the secret
    """
    if secret_key in _secrets:
        return _secrets[secret_key]

    if hidden:
        secret = getpass(message)
    else:
        secret = input(message)

    if secret.strip():
        _secrets[secret_key] = secret.strip()
        save_secrets()

    return secret


save_secrets()
