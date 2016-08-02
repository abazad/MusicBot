# TelegramMusicBot
This bot lets users select songs from Google Play Music to play on the bot host machine

## Installation:
- Works only with Python 3+
- Should be completely platform independent, as long as all dependencies are available
  - tested on Raspbian, Ubuntu, Windows
- You'll need to provide in the secrets.json:
  - your Google username/email and password
  - your android device id from a phone you accessed play music on once
  - a telegram bot token retrieved from the [BotFather](https://telegram.me/botfather)
    - enable inline mode with /setinline
    - enable inline feedback with /setinlinefeedback
    - this bot does not work well in groups, so disable /setjoingroups
    - you can also give the BotFather a list of commands with /setcommands
  - if you want to queue youtube songs:
    - a youtube api key
    - a telegram bot token for a second bot
      - this bot will only handle inline queries, no commands
      - except for the commands list, the bot should be configured exactly like the GMusic bot
  - if you want to queue soundcloud songs:
    - a soundcloud [app id](http://soundcloud.com/you/apps)
    - a telegram bot token for a third bot
      - this bot will only handle inline queries, no commands
      - except for the commands list, the bot should be configured exactly like the GMusic bot
- For further installation instructions, see the installation files for [Windows](INSTALLATION_windows.md) or [Linux](INSTALLATION_linux.md)

## Commands:
* /currentsong - shows the name of the currently playing song
* /showqueue - show current queue
* /next - skip current song
* /movesong - move a song in the queue
* /skip - skip a song in the queue
* /cancel - hide the reply keyboard
* /pause - pause playback
* /play - resume playback
* /login - login into a password protected session
* /subscribe - subscribe to queue updates
* /unsubscribe - unsubscribe from queue updates

### Admin commands (should not be sent to the botfather)
* /admin - register as admin (only possible once)
* /clearqueue - clear the current queue
* /ip - get the bot's local IP address
* /reset - delete the BotPlaylist and BotStation on google play music, reset the admin setting and stop the bot
* /stop - stop the bot
* /togglepassword - toggles the session password on and off
* /setpassword [password] - sets the session password
* /banuser - bans a user from the current session and resets the password
* /setquality [hi/med/low] - sets the gmusic song quality

## Dependencies:
  - [colorama](https://github.com/tartley/colorama)
  - [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
  - [gmusicapi](https://github.com/simon-weber/gmusicapi)
  - [pydub](https://github.com/jiaaro/pydub)
  - [simpleaudio](https://github.com/hamiltron/py-simple-audio)
  - [pylru](https://github.com/jlhutch/pylru)
  - If you want to be able to queue youtube songs
    - [pafy](https://github.com/mps-youtube/pafy)
    - [youtube-dl](https://github.com/rg3/youtube-dl)
  - If you want to be able to queue soundcloud songs
    - [soundcloud](https://github.com/soundcloud/soundcloud-python)

## Additional commands
The TelegramMusicBot allows you to add additional Commands to your Bot.
Simply drop a .py-file with a `get_label`- and a `run_command`-function into the plugins-directory.

Following is an example of a command hat allows you to control the volume on a linux-system:
```
from subprocess import call
from bot import password_protected_command

#Return the command label. This method has to be implemented!
def get_label():
    return 'volume'


#Implements your Command. This method has to be implemented!
@password_protected_command
def run_command(bot, update):
    chat_id = update.message.chat_id
    split = update.message.text.split(" ")
    if not len(split) == 2:
        bot.send_message(
        chat_id=chat_id, text="Usage: /volume [0-100]")
        return

    try:
        volume = int(split[1])
    except ValueError:
        bot.send_message(chat_id=chat_id, text="Parameter has to be an Integer")
        return

    if volume in range(0,101):
        call(["amixer", "-D", "pulse", "sset", "Master", str(volume)+"%"])
        bot.send_message(chat_id=chat_id, text="Volume changed")
        return

    bot.send_message(chat_id=chat_id, text="Invalid parameter")
    return
```

Note that you have to send the [BotFather](https://telegram.me/botfather) your additional commands to have them shown in the command-list.
