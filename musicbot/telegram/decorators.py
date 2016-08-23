import logging

from musicbot.telegram.user import User


def plugin_command(func):
    def _command(_, *args):
        return func(*args)
    return _command


def admin_command(func):
    def _command(self, bot, update):
        if self._options.admin_chat_id == update.message.chat_id:
            return func(self, bot, update)
        else:
            bot.send_message(chat_id=update.message.chat_id, text="This command is for admins only")
            return None
    return _command


def password_protected_command(func):
    def _command(self, bot, update):
        options = self._options
        chat_id = update.message.chat_id
        if options.enable_password and not options.password:
            bot.send_message(chat_id=chat_id, text="Admin hasn't decided which password to use yet")
            return None
        user = User(user=update.message.from_user)
        if (not options.enable_password) or (user in options.clients):
            return func(self, bot, update)
        else:
            bot.send_message(chat_id=chat_id, text="Please log in with /login [password]")
            return None

    return _command


def queue_action_command(question="What song?", min_len=1, song_queue=None):
    def _decorator(func):
        def _command(self, bot, update):

            chat_id = update.message.chat_id
            player = self._player
            queue = song_queue or player.get_queue()
            # Clone the queue
            queue = list(queue)

            if len(queue) < min_len:
                bot.send_message(chat_id=chat_id, text="Not enough songs in queue")
                return

            queue_songs = {song.song_id: song for song in queue}

            @callback_keyboard_answer_handler
            def _action(chat_id, data):
                song = queue_songs[data]
                return func(self, chat_id, song)

            keyboard_items = self.get_queue_keyboard_items(queue)
            self.send_callback_keyboard(bot, chat_id, question, keyboard_items, _action)
        return _command
    return _decorator


def keyboard_answer_handler(func):
    def _handler(bot, update):
        text = update.message.text
        if ")" not in text:
            return False
        c = text.split(")")[0]
        if str.isdecimal(c):
            return func(int(c))
        else:
            logging.getLogger("musicbot").debug("INVALID CHOICE: %s", c)
            return False
    return _handler


def callback_keyboard_answer_handler(func):
    def _handler(bot, update):
        query = update.callback_query
        chat_id = query.message.chat.id
        data = query.data
        if not data:
            logging.getLogger("musicbot").debug("missing data for callback query")
            return True
        return func(chat_id, data)
    return _handler
