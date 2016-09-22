import logging
import socket
import sys
import time

import telegram
from pylru import lrucache
from telegram.ext import dispatcher
from telegram.ext import updater
from telegram.ext.callbackqueryhandler import CallbackQueryHandler
from telegram.ext.choseninlineresulthandler import ChosenInlineResultHandler
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.inlinequeryhandler import InlineQueryHandler
from telegram.ext.messagehandler import MessageHandler, Filters
from telegram.inlinekeyboardbutton import InlineKeyboardButton
from telegram.inlinekeyboardmarkup import InlineKeyboardMarkup
from telegram.inlinequeryresultarticle import InlineQueryResultArticle
from telegram.replykeyboardhide import ReplyKeyboardHide
from telegram.replykeyboardmarkup import ReplyKeyboardMarkup

from musicbot import async_handler
from musicbot import config
from musicbot import music_apis
from musicbot.telegram import decorators, notifier
from musicbot.telegram.user import User


def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]


admin_commands = ["clearqueue", "ip", "togglepassword", "setpassword", "banuser", "setquality",
                  "stationremove", "stationreload", "reset", "exit"]

_clients = set()
_password = None


class TelegramBot(notifier.Subscribable):
    def __init__(self, plugins, music_api, song_provider, player):
        self._music_api = music_api
        self._song_provider = song_provider
        self._player = player
        self._sent_keyboard = {}
        self._sent_keyboard_message_ids = {}

        token_key = "telegram_" + music_api.get_name() + "_bot_token"
        token = config.request_secret(token_key,
                                      "Please provide a telegram token for the {} bot (leave empty if unwanted): ".format(
                                          music_api.get_pretty_name()))
        if not token:
            raise ValueError("No token given")

        self._updater = updater.Updater(token=token)

        _dispatcher = self._updater.dispatcher
        self._register_commands(_dispatcher, plugins)
        self._updater.start_polling()

        async_handler.execute(None, self._updater.stop)

    def _register_commands(self, _dispatcher, plugins):
        # keyboard answer handlers
        _dispatcher.add_handler(MessageHandler([Filters.text], self.handle_message))
        _dispatcher.add_handler(CallbackQueryHandler(self.handle_callback_query))

        # public commands
        _dispatcher.add_handler(CommandHandler('start', self.start_command))
        _dispatcher.add_handler(CommandHandler('showqueue', self.show_queue_command))
        _dispatcher.add_handler(CommandHandler('currentsong', self.current_song_command))
        _dispatcher.add_handler(CommandHandler('cancel', self.cancel_command))
        _dispatcher.add_handler(CommandHandler('login', self.login_command))

        _dispatcher.add_handler(CommandHandler('subscribe', self.subscribe))
        _dispatcher.add_handler(CommandHandler('unsubscribe', self.unsubscribe))

        # gmusic_password protected commands
        _dispatcher.add_handler(CommandHandler('next', self.next_command))
        _dispatcher.add_handler(CommandHandler('play', self.play_command))
        _dispatcher.add_handler(CommandHandler('pause', self.pause_command))
        _dispatcher.add_handler(CommandHandler('skip', self.skip_command))
        _dispatcher.add_handler(CommandHandler('movesong', self.move_song_command))

        # admin commands
        _dispatcher.add_handler(CommandHandler('admin', self.admin_command))
        _dispatcher.add_handler(CommandHandler('clearqueue', self.clear_queue_command))
        _dispatcher.add_handler(CommandHandler('reset', self.reset_command))
        _dispatcher.add_handler(CommandHandler('exit', self.exit_command))
        _dispatcher.add_handler(CommandHandler('ip', self.ip_command))
        _dispatcher.add_handler(CommandHandler('togglepassword', self.toggle_password_command))
        _dispatcher.add_handler(CommandHandler('setpassword', self.set_password_command))
        _dispatcher.add_handler(CommandHandler('banuser', self.ban_user_command))
        _dispatcher.add_handler(CommandHandler('setquality', self.set_quality_command))
        _dispatcher.add_handler(CommandHandler('stationremove', self.station_remove_command))
        _dispatcher.add_handler(CommandHandler('stationreload', self.station_reload_command))

        for plugin in plugins:
            _dispatcher.add_handler(
                CommandHandler(plugin.get_label(), lambda bot, update: plugin.run_command(self, bot, update)))

        _dispatcher.add_handler(InlineQueryHandler(self.get_inline_query_handler()))
        _dispatcher.add_handler(ChosenInlineResultHandler(self.queue_command))

    def send_keyboard(self, bot, chat_id, text, items, action=None):
        keyboard = []
        for item in items:
            keyboard.append([item])

        keyboard.append(["/cancel"])

        markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)

        if action:
            self._sent_keyboard[chat_id] = action

    def send_callback_keyboard(self, bot, chat_id, text, buttons, action=None):
        keyboard = []
        for button in buttons:
            keyboard.append([button])
        keyboard.append([InlineKeyboardButton("cancel", callback_data="null")])

        markup = InlineKeyboardMarkup(keyboard)

        try:
            message_id = self._sent_keyboard_message_ids[chat_id]
            message = bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        except KeyError:
            message = bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)

        self._sent_keyboard_message_ids[chat_id] = message.message_id

        if action:
            self._sent_keyboard[chat_id] = action

    def hide_keyboard(self, bot, chat_id, message="kk...", parse_mode="markdown", message_id=None):
        try:
            old_message_id = message_id or self._sent_keyboard_message_ids[chat_id]
            bot.edit_message_text(chat_id=chat_id, message_id=old_message_id, text=message, parse_mode=parse_mode)
        except KeyError:
            markup = ReplyKeyboardHide()
            bot.send_message(chat_id=chat_id, text=message, reply_markup=markup, parse_mode=parse_mode)

    def cancel_command(self, bot, update):
        chat_id = update.message.chat_id
        if chat_id in self._sent_keyboard:
            del self._sent_keyboard[chat_id]
        if chat_id in self._sent_keyboard_message_ids:
            del self._sent_keyboard_message_ids[chat_id]
        self.hide_keyboard(bot, chat_id)

    def handle_message(self, bot, update):
        chat_id = update.message.chat_id
        if chat_id in self._sent_keyboard:
            action = self._sent_keyboard[chat_id]
            result = action(bot, update)
            if result:
                self.hide_keyboard(bot, chat_id, result)
                del self._sent_keyboard[chat_id]

    def handle_callback_query(self, bot, update):
        query = update.callback_query
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        data = query.data

        if not data:
            logging.getLogger("musicbot").debug("missing data for callback query")
            self.hide_keyboard(bot, chat_id, message_id=message_id)
            return

        if data == "null":
            self.hide_keyboard(bot, chat_id, message_id=message_id)
            try:
                sent_keyboard_message_ids = self._sent_keyboard_message_ids
                if sent_keyboard_message_ids[chat_id] == message_id:
                    del sent_keyboard_message_ids[chat_id]
            except KeyError:
                pass
            return

        try:
            action = self._sent_keyboard[chat_id]
        except KeyError:
            logging.getLogger("musicbot").debug("Found no action for callback query")
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="error")
            return

        try:
            if message_id == self._sent_keyboard_message_ids[chat_id]:
                if action:
                    result = action(bot, update)
                    if result:
                        self.hide_keyboard(bot, chat_id, result)
                        del self._sent_keyboard[chat_id]
                        del self._sent_keyboard_message_ids[chat_id]
        except KeyError:
            logging.getLogger("musicbot").debug("Received query for unknown message id (%s)", message_id)
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="error")

    def is_logged_in(self, telegram_user):
        user = User(user=telegram_user)
        return (not config.get_telegram_password_enabled()) or (user in _clients)

    def get_current_song_message(self):
        return "Now playing: {}".format(self._player.get_current_song())

    def get_queue_message(self):
        queue = self._player.get_queue()
        message = "\n"
        header_str = "*Current queue:*"
        if len(queue) > 0:
            message = header_str + "\n" + message.join(map(str, queue))
        else:
            message = message.join([header_str, "_empty..._"])
        return message

    def get_queue_keyboard_items(self, queue=None):
        if not queue:
            queue = self._player.get_queue()
        for song in queue:
            yield InlineKeyboardButton(text=str(song), callback_data=song.song_id)

    def start_command(self, bot, update):
        chat_id = update.message.chat_id
        if not self.is_logged_in(update.message.from_user):
            bot.send_message(chat_id=chat_id,
                             text="Please log in with /login [password].\nYou can long press /login to not send it immediately.")
            return

        text = "Type {} and search for a song.".format(bot.name)
        bot.send_message(chat_id=chat_id, text=text)

    def login_command(self, bot, update):
        chat_id = update.message.chat_id
        user = update.message.from_user
        if not config.get_telegram_password_enabled():
            bot.send_message(chat_id=chat_id, text="There is no password")
            return

        if user.id in _clients:
            bot.send_message(chat_id=chat_id, text="You are already logged in")
            return

        if not _password:
            bot.send_message(chat_id=chat_id, text="Admin hasn't decided which password to use yet")
            return

        split = update.message.text.split(" ")
        if len(split) < 2:
            bot.send_message(chat_id=chat_id, text="Usage: /login [password]")
            return

        password = split[1].strip()
        if not password:
            bot.send_message(chat_id=chat_id, text="Password can't be empty")
            return

        if password == _password:
            _clients.add(User(user=user))
            bot.send_message(chat_id=chat_id, text="Successfully logged in")
        else:
            bot.send_message(chat_id=chat_id, text="Wrong password")

    def show_queue_command(self, bot, update):
        message = self.get_queue_message()
        bot.send_message(chat_id=update.message.chat_id, text=message, parse_mode="markdown")

    def current_song_command(self, bot, update):
        bot.send_message(chat_id=update.message.chat_id, text=self.get_current_song_message())

    def admin_command(self, bot, update):
        chat_id = update.message.chat_id
        secrets = config.get_secrets()
        admin_key = "telegram_admin_chat_id"
        if not secrets.get(admin_key, 0):
            secrets[admin_key] = chat_id
            config.save_secrets()
            text = "You're admin now!"
        elif chat_id == secrets[admin_key]:
            text = "You already are admin!"
        else:
            bot.send_message(text="There can be only one!", chat_id=chat_id)
            return
        text += "\nHidden comamnds:\n/" + "\n/".join(admin_commands)
        bot.send_message(text=text, chat_id=chat_id)

    # Password protected commands
    @dispatcher.run_async
    @decorators.password_protected_command
    @decorators.queue_action_command(question="What song do you want to skip?")
    def skip_command(self, chat_id, song):
        self._player.skip_song(song)
        return self.get_queue_message()

    @dispatcher.run_async
    @decorators.password_protected_command
    def move_song_command(self, bot, update):
        @decorators.queue_action_command("What song do you want to move?", 2)
        def _first_action(self, chat_id, source):
            queue = self._player.get_queue()
            filtered_queue = filter(lambda song: song != source, queue)

            @decorators.queue_action_command("Before what song should it be?", 1, filtered_queue)
            def _second_action(self, chat_id, target):
                queue.remove(source)
                index = queue.index(target)
                queue.insert(index, source)
                return self.get_queue_message()

            _second_action(self, bot, update)
            return False

        return _first_action(self, bot, update)

    @dispatcher.run_async
    @decorators.password_protected_command
    def play_command(self, bot, update):
        self._player.resume()

    @decorators.password_protected_command
    def pause_command(self, bot, update):
        self._player.pause()

    @dispatcher.run_async
    @decorators.password_protected_command
    def next_command(self, bot, update):
        self._player.next()
        if not self.is_subscriber(update.message.chat_id):
            self.current_song_command(bot, update)

    def get_inline_query_handler(self):
        generators_cache = lrucache(256)
        lists_cache = lrucache(256)
        max_len = 20

        def _get_inline_result_article(song):
            title = song.title
            description = song.description

            if not description:
                description = ""
            else:
                description = description[:128]

            duration = song.duration
            if duration:
                description = "{}\n{}".format(description, duration)

            result = InlineQueryResultArticle(
                id=song.song_id,
                title=title,
                description=description,
                input_message_content=telegram.InputTextMessageContent(str(song))
            )

            url = song.albumArtUrl
            if url:
                result.thumb_url = url
            return result

        @dispatcher.run_async
        def _handler(bot, update):
            if not self.is_logged_in(update.inline_query.from_user):
                return

            offset = update.inline_query.offset
            if offset:
                offset = int(offset)
            else:
                offset = 0
            query = update.inline_query.query
            api = self._music_api

            suggest = config.get_suggest_songs_enabled() and isinstance(api, music_apis.AbstractSongProvider)
            if query and query.strip():
                query = query.strip()
                try:
                    song_generator = generators_cache[query]
                except KeyError:
                    song_generator = api.search_song(query)
                    generators_cache[query] = song_generator
                    lists_cache[query] = []

                song_list = lists_cache[query]
                song_list_len = len(song_list)

                next_offset = offset + max_len
                while next_offset >= song_list_len:
                    try:
                        song_list.append(song_generator.__next__())
                        song_list_len += 1
                    except StopIteration:
                        next_offset = 0
                        break

                # set server-side caching time to default (300 seconds)
                cache_time = 300

                song_list = song_list[offset:]
                song_list = song_list[:max_len]
            elif suggest:
                song_list = api.get_suggestions(max_len=15)
                cache_time = 20
                next_offset = 0
            else:
                return

            # Filter duplicate songs
            seen = set()
            seen_add = seen.add

            def _seen_add(song):
                if song in seen:
                    return False
                else:
                    seen_add(song)
                    return True

            song_list = filter(_seen_add, song_list)

            results = list(map(_get_inline_result_article, song_list))
            bot.answerInlineQuery(update.inline_query.id, results, cache_time=cache_time, next_offset=next_offset)

        return _handler

    @dispatcher.run_async
    def queue_command(self, bot, update):
        song_id = update.chosen_inline_result["result_id"]
        user = update.chosen_inline_result["from_user"]

        if not self.is_logged_in(user):
            return

        song = self._music_api.lookup_song(song_id)
        username = user["first_name"]
        logging.getLogger("musicbot").info("QUEUED by %s: %s", username, song)
        song.user = username
        self._player.queue(song)

    # Admin commands
    @decorators.admin_command
    def clear_queue_command(self, bot, update):
        self._player.clear_queue()

    @decorators.admin_command
    def reset_command(self, bot, update):
        self._song_provider.reset()
        del config.get_secrets()['telegram_admin_chat_id']
        config.save_secrets()

        def _exit():
            async_handler.shutdown(False)
            time.sleep(1)
            sys.exit(0)

        async_handler.submit(_exit)

    @dispatcher.run_async
    @decorators.admin_command
    def ip_command(self, bot, update):
        chat_id = update.message.chat_id
        text = "IP-Address: {}".format(get_ip_address())
        bot.send_message(text=text, chat_id=chat_id)

    @decorators.admin_command
    def toggle_password_command(self, bot, update):
        chat_id = update.message.chat_id
        if config.get_telegram_password_enabled():
            config.set_telegram_password_enabled(False)
            _clients.clear()
            global _password
            _password = None
            bot.send_message(chat_id=chat_id, text="Password disabled")
        else:
            config.set_telegram_password_enabled(True)
            bot.send_message(
                chat_id=chat_id, text="Password is now enabled. Set a password with /setpassword [password]")

    @decorators.admin_command
    def set_password_command(self, bot, update):
        chat_id = update.message.chat_id
        if not config.get_telegram_password_enabled():
            bot.send_message(chat_id=chat_id, text="Please enable password protection with /togglepassword first")
            return

        split = update.message.text.split(" ")
        if len(split) < 2:
            bot.send_message(chat_id=chat_id, text="Usage: /setpassword [password]")
            return

        password = split[1].strip()
        if not password:
            bot.send_message(chat_id=chat_id, text="Password can't be empty")
            return

        global _password
        _password = password
        _clients.add(User(user=update.message.from_user))
        bot.send_message(chat_id=chat_id, text="Successfully changed password")

    @dispatcher.run_async
    @decorators.admin_command
    def ban_user_command(self, bot, update):
        chat_id = update.message.chat_id

        if not config.get_telegram_password_enabled():
            bot.send_message(chat_id=chat_id, text="Password is disabled")
            return

        if not _clients:
            bot.send_message(chat_id=chat_id, text="No clients logged in")
            return

        text = "Who should be banned?"
        keyboard_items = list(
            map(lambda client: InlineKeyboardButton(text=client.name, callback_data=str(client.user_id)), _clients))

        @decorators.callback_keyboard_answer_handler
        def _action(chat_id, data):
            global _clients
            global _password
            _clients = set(filter(lambda client: str(client.user_id) != data, _clients))
            _password = None
            return "Banned user. Please set a new password."

        self.send_callback_keyboard(bot, chat_id, text, keyboard_items, _action)

    @decorators.admin_command
    def set_quality_command(self, bot, update):
        chat_id = update.message.chat_id
        split = update.message.text.split(" ")
        if len(split) < 2:
            bot.send_message(chat_id=chat_id, text="Usage: /setquality [hi/med/low]")
            return

        quality = split[1]
        try:
            self._music_api.set_quality(quality)
            config.set_gmusic_quality(quality)
            bot.send_message(chat_id=chat_id, text="Successfully changed quality")
        except ValueError:
            bot.send_message(chat_id=chat_id, text="Invalid quality")
            return

    @decorators.admin_command
    def exit_command(self, bot, update):
        def _exit():
            async_handler.shutdown(False)
            time.sleep(1)
            sys.exit(0)

        async_handler.submit(_exit)

    @dispatcher.run_async
    @decorators.admin_command
    def station_remove_command(self, bot, update):
        chat_id = update.message.chat_id
        api = self._song_provider
        playlist = api.get_playlist()

        if not playlist:
            bot.send_message(chat_id=chat_id, text="The playlist is empty.")
            return

        @decorators.callback_keyboard_answer_handler
        def _action(chat_id, data):
            song = api.lookup_song(data)

            if song not in playlist:
                bot.send_message(chat_id=chat_id, text="That song is not in the BotPlaylist")

            api.remove_from_playlist(song)
            return "Removed from playlist: " + str(song)

        keyboard_items = map(lambda song: InlineKeyboardButton(
            str(song), callback_data=song.song_id), sorted(playlist))

        self.send_callback_keyboard(bot, chat_id, "What song should be removed?", keyboard_items, _action)

    @decorators.admin_command
    def station_reload_command(self, bot, update):
        # Drop the pre-fetched next_songs list. The list will be refilled when needed.
        self._song_provider.reload()
        bot.send_message(chat_id=update.message.chat_id, text="Reloaded station songs.")

    def idle(self):
        self._updater.idle()

    def get_clients(self):
        return _clients

    def get_password(self):
        return _password
