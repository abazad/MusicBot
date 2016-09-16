import logging
import os
import signal
import sys
from datetime import datetime
from getpass import getpass

import colorama

from musicbot import async_handler
from musicbot import config
from musicbot import music_apis
from musicbot import player
from musicbot.plugin_handler import PluginLoader
from musicbot.telegram import bot

# Initialize colorama for colored output
colorama.init()

# Initialize logger
os.makedirs("logs", exist_ok=True)

logging.getLogger().addHandler(logging.NullHandler())
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

# Load additional Telegram Commands
if config.get_load_plugins_enabled():
    plugin_loader = PluginLoader()
    plugin_loader.load_plugins()
    plugins = plugin_loader.get_plugins()
else:
    plugins = []

# Check for updates
if config.get_auto_updates_enabled():
    logger.info("Checking for updates...")
    import updater

    if updater.update():
        logger.info("Restarting after update...")
        os.execl(sys.executable, sys.executable, *sys.argv)
        sys.exit(0)
    else:
        logger.info("No updates found.")

secrets = config.get_secrets()

music_api_list = []

# Load Telegram Bots
try:
    gmusic_api = music_apis.GMusicAPI()
    music_api_list.append(gmusic_api)
except ValueError as e:
    logger.critical("Error accessing GMusic. (%s)", e)
    async_handler.shutdown()
    sys.exit(3)

try:
    soundcloud_api = music_apis.SoundCloudAPI()
    music_api_list.append(soundcloud_api)
except ValueError as e:
    logger.warning("SoundCloud unavailable. (%s)", e)
    soundcloud_api = None

try:
    youtube_api = music_apis.YouTubeAPI()
    music_api_list.append(youtube_api)
except ValueError as e:
    logger.warning("YouTube unavailable. (%s)", e)
    youtube_api = None

queued_player = player.Player(gmusic_api)

try:
    gmusic_bot = bot.TelegramBot(plugins, gmusic_api, gmusic_api, queued_player)
except ValueError:
    logger.info("GMusic telegram bot unavailable.")

try:
    if soundcloud_api:
        soundcloud_bot = bot.TelegramBot(plugins, soundcloud_api, gmusic_api, queued_player)
except ValueError:
    logger.info("SoundCloud telegram bot unavailable.")

try:
    if youtube_api:
        youtube_bot = bot.TelegramBot(plugins, youtube_api, gmusic_api, queued_player)
except ValueError:
    logger.info("YouTube telegram bot unavailable.")

if "--no-rest" not in sys.argv:
    import ssl

    from aiohttp import web
    from aiohttp_wsgi import WSGIHandler

    from musicbot import rest_api

    rest_api.init(music_api_list, queued_player)

    cert_path = "config/ssl.cert"
    key_path = "config/ssl.key"
    if not (os.path.isfile(cert_path) and os.path.isfile(key_path)):
        logger.critical("MISSING SSL FILES (ssl.cert and ssl.key in config directory)")
        async_handler.shutdown()
        sys.exit(4)

    try:
        wsgi_handler = WSGIHandler(rest_api.__hug_wsgi__)
        app = web.Application()
        app.router.add_route("*", "/{path_info:.*}", wsgi_handler)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)

        _password = getpass("Enter SSL key password: ")
        ssl_context.load_cert_chain(cert_path, key_path, password=_password)
        queued_player.run()


        def _exit():
            app.shutdown()
            app.cleanup()


        async_handler.execute(None, _exit)
        web.run_app(app, ssl_context=ssl_context)
    except:
        pass
else:
    queued_player.run()
    signal.sigwait({signal.SIGINT, signal.SIGTERM})

async_handler.shutdown()
sys.exit(0)
