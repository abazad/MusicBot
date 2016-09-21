import json
import locale
import logging
from getpass import getpass
from os import path

import jwt

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


def _get_secrets_path():
    secrets_dir = path.expanduser(_config.get("secrets_location", "config"))
    return path.join(secrets_dir, "secrets.dat")


def _load_secrets():
    secrets_path = _get_secrets_path()
    if not path.isfile(secrets_path):
        logging.getLogger("musicbot").debug("No secrets file found")
        return {}
    with open(secrets_path, 'rb') as secrets_file:
        return jwt.decode(secrets_file.read(), _secrets_password, algorithm="HS256")


if _version.debug:
    _secrets_password = "testpw"
else:
    _secrets_password = getpass("Enter secrets password: ")
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
    with open(secrets_path, 'wb') as secrets_file:
        secrets_file.write(jwt.encode(_secrets, _secrets_password, algorithm="HS256"))
