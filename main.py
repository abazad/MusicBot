from datetime import datetime
import json
import logging
import os
import sys

import colorama

from musicbot import music_apis, player
from musicbot.plugin_handler import PluginLoader
from musicbot.telegram import bot


# Initialize colorama for colored output
colorama.init()

# Initialize logger
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("musicbot")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "%(asctime)s (%(levelname)s, %(filename)s:%(lineno)s): %(message)s", datefmt="%H:%M:%S")

file_handler = logging.FileHandler(
    datetime.utcnow().strftime("logs/%Y%m%d-%H%M%S.log"), encoding="utf-8", mode='w')
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

# Load config
config_dir = "config"
options = bot.TelegramOptions(config_dir)

if options.load_plugins:
    # Load additional Commands
    plugin_loader = PluginLoader()
    plugin_loader.load_plugins()
    plugins = plugin_loader.get_plugins()
else:
    plugins = []

try:
    with open(options.secrets_path, "r") as secrets_file:
        secrets = json.loads(secrets_file.read())
        secrets = {k: str.strip(v) for k, v in secrets.items()}
        try:
            gmusic_token = secrets["gmusic_bot_token"]
        except KeyError:
            print("Missing GMusic token")
            sys.exit(1)

        youtube_token = secrets.get("youtube_bot_token", None)
        soundcloud_token = secrets.get("soundcloud_bot_token", None)
except IOError:
    print("Could not open secrets.json")
    sys.exit(2)

with open(os.path.join(config_dir, "config.json"), 'r') as config_file:
    config = json.loads(config_file.read())

apis = []

try:
    gmusic_api = music_apis.GMusicAPI(config_dir, config, secrets)
    apis.append(gmusic_api)
    if soundcloud_token:
        soundcloud_api = music_apis.SoundCloudAPI(config_dir, config, secrets)
        apis.append(soundcloud_api)
    if youtube_token:
        youtube_api = music_apis.YouTubeAPI(config_dir, config, secrets)
        apis.append(youtube_api)
except KeyError as e:
    print(e)
    sys.exit(3)

queued_player = player.Player(gmusic_api)

if config.get("auto_updates", False):
    logger.info("Checking for updates...")
    import updater
    if updater.update():
        logger.info("Restarting after update...")
        os.execl(sys.executable, sys.executable, *sys.argv)
        sys.exit(0)
    else:
        logger.info("No updates found.")

gmusic_bot = bot.TelegramBot(options, gmusic_token, plugins, gmusic_api, gmusic_api, queued_player)

if youtube_token:
    youtube_bot = bot.TelegramBot(options, youtube_token, plugins, youtube_api, gmusic_api, queued_player)

if soundcloud_token:
    soundcloud_bot = bot.TelegramBot(options, soundcloud_token, plugins, soundcloud_api, gmusic_api, queued_player)


def run():
    queued_player.run()


if(__name__ == "__main__"):
    run()
    gmusic_bot.idle()
    sys.exit(0)
