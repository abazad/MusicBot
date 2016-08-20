import json
import os
import signal
import sys

import colorama

from musicbot import music_apis, player
from musicbot.plugin_handler import PluginLoader
from musicbot.telegram import bot, decorators


# Initialize colorama for colored output
colorama.init()


config_dir = "config"
options = bot.TelegramOptions(config_dir)
decorators.init(options)


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

try:
    gmusic_api = music_apis.GMusicAPI(config_dir, config, secrets)
    if soundcloud_token:
        soundcloud_api = music_apis.SoundCloudAPI(config_dir, config, secrets)
    if youtube_token:
        youtube_api = music_apis.YouTubeAPI(config_dir, config, secrets)
except KeyError as e:
    print(e)
    sys.exit(3)

queued_player = player.Player(gmusic_api)


if config.get("auto_updates", False):
    print("Checking for updates...")
    import updater
    with open(os.devnull, 'w') as devnull:
        if updater.update(output=devnull):
            print("Restarting after update...")
            os.execl(sys.executable, sys.executable, *sys.argv)
            sys.exit(0)
        else:
            print("No updates found.")

gmusic_bot = bot.TelegramBot(options, gmusic_token, plugins, gmusic_api, gmusic_api, queued_player)

if youtube_token:
    youtube_bot = bot.TelegramBot(options, youtube_token, plugins, youtube_api, gmusic_api, queued_player)
else:
    youtube_updater = True

if soundcloud_token:
    soundcloud_bot = bot.TelegramBot(options, soundcloud_token, plugins, soundcloud_api, gmusic_api, queued_player)
else:
    soundcloud_updater = True

queued_player.run()

try:
    gmusic_bot.idle()
except InterruptedError:
    pass
os.kill(os.getpid(), signal.SIGINT)
