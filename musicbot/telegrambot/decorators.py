from musicbot.telegrambot.user import User


_options = None


def init(options):
    global _options
    if _options:
        raise ValueError("Already initialized")
    _options = options


def admin_command(func):
    def _admin_func(*args):
        if len(args) == 3:
            # Ignore self argument
            i = 1
        else:
            i = 0

        bot = args[i]
        update = args[i + 1]

        if _options.admin_chat_id == update.message.chat_id:
            return func(*args)
        else:
            bot.send_message(chat_id=update.message.chat_id, text="This command is for admins only")
            return None
    return _admin_func


def password_protected_command(func):
    def _password_protected_func(*args):
        if len(args) == 3:
            # Ignore self argument
            i = 1
        else:
            i = 0

        bot = args[i]
        update = args[i + 1]

        chat_id = update.message.chat_id
        if _options.enable_password and not _options.password:
            bot.send_message(chat_id=chat_id, text="Admin hasn't decided which password to use yet")
            return None
        user = User(user=update.message.from_user)
        if (not _options.enable_password) or (user in _options.clients):
            return func(*args)
        else:
            bot.send_message(chat_id=chat_id, text="Please log in with /login [password]")
            return None

    return _password_protected_func


def keyboard_answer_handler(func):
    def _handler(bot, update):
        text = update.message.text
        if ")" not in text:
            return False
        c = text.split(")")[0]
        if str.isdecimal(c):
            return func(int(c))
        else:
            print("INVALID CHOICE:", c)
            return False
    return _handler
