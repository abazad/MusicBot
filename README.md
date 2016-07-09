# TelegramMusicBot
This bot lets users select songs from Google Play Music to play on the bot host machine

## Installation:
- Works with Python 3+
- You'll need to provide in the secrets.json:
  - your Google username/email and password
  - your android device id from a phone you accessed play music on once
  - a telegram bot token retrieved from the [BotFather](https://telegram.me/botfather)
    - enable inline mode with /setinline
    - enable inline feedback with /setinline
    - this bot does not work well in groups, so disable /setjoingroups

## Commands:
* pause - pause playback
* play - resume playback
* next - skip current song
* currentsong - shows the name of the currently playing song
* skip - skip a song in the queue
* movesong - move a song in the queue
* showqueue - show current queue
* clearqueue - clear the current queue

## Dependencies:
  - [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
  - [gmusicapi](https://github.com/simon-weber/gmusicapi)
  
## Contributions:
All contributions are welcome, please make pull requests against the dev branch
