# TelegramMusicBot
This bot plays songs from Google Play Music, YouTube or Soundcloud selected by users via Telegram.  

## Build status:
branch | status
------ | ------
master | [![CircleCI](https://circleci.com/gh/BjoernPetersen/TelegramMusicBot/tree/master.svg?style=svg)](https://circleci.com/gh/BjoernPetersen/TelegramMusicBot/tree/master)  
dev | [![CircleCI](https://circleci.com/gh/BjoernPetersen/TelegramMusicBot/tree/dev.svg?style=svg)](https://circleci.com/gh/BjoernPetersen/TelegramMusicBot/tree/dev)

## Installation:
- See [Installation](../../wiki/Installation) and [Configuration](../../wiki/Configuration) wiki pages.

## Commands:
See the [Bot usage](../../wiki/Bot-usage) wiki page.

## Additional commands:
You can add custom commands by following the instructions on the [Adding commands](../../wiki/Adding-commands) wiki page.

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


