from enum import Enum


class _Subscriber(object):

    def __init__(self, chat_id, bot, silent=False):
        self.chat_id = chat_id
        self._bot = bot
        self._silent = silent

    def notify(self, cause):
        if self._bot:
            self._bot.send_message(chat_id=self.chat_id, text=cause, disable_notification=self._silent)

    def __hash__(self):
        return hash(self.chat_id)

    def __eq__(self, other):
        return self.chat_id == other.chat_id


class Subscribable(object):

    def subscribe(self, bot, update):
        chat_id = update.message.chat_id

        if _Subscriber(chat_id, bot) in Notifier._subscribers:
            bot.send_message(chat_id=chat_id, text="Already subscribed.")
            return

        def _action(bot, update):
            text = update.message.text.lower()
            if "y" in text:
                silent = False
            else:
                silent = True

            subscriber = _Subscriber(chat_id, bot, silent)
            Notifier._subscribers.add(subscriber)
            self.hide_keyboard(bot, chat_id, "Subscribed.")
            return True

        keyboard_items = ["Yes", "No"]
        self.send_keyboard(bot, chat_id, "Do you want to receive notifications?", keyboard_items, _action)

    def unsubscribe(self, bot, update):
        chat_id = update.message.chat_id
        subscriber = _Subscriber(chat_id, bot)
        if subscriber in Notifier._subscribers:
            Notifier._subscribers.remove(subscriber)
        bot.send_message(chat_id=chat_id, text="Unsubscribed.")

    def is_subscriber(self, chat_id):
        return _Subscriber(chat_id, None) in Notifier._subscribers

    def hide_keyboard(self, *args, **kwargs):
        raise NotImplementedError()

    def send_keyboard(self, *args, **kwargs):
        raise NotImplementedError()


class Cause(Enum):
    current_song = lambda song: "Now playing: " + str(song)
    queue_add = lambda song: "Added to queue: " + str(song)
    queue_remove = lambda song: "Removed from queue: " + str(song)


class Notifier(object):
    _subscribers = set()

    def __init__(self):
        pass

    @classmethod
    def notify(cls, cause):
        for subscriber in cls._subscribers:
            subscriber.notify(cause)
