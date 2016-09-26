# MusicBot
This bot plays songs from Google Play Music, YouTube or SoundCloud selected by users via Telegram or the [AndroidMusicBot app](https://github.com/BjoernPetersen/AndroidMusicBot).  

## Build status:
branch | status
------ | ------
master | [![CircleCI](https://circleci.com/gh/BjoernPetersen/MusicBot/tree/master.svg?style=svg)](https://circleci.com/gh/BjoernPetersen/MusicBot/tree/master)  
dev | [![CircleCI](https://circleci.com/gh/BjoernPetersen/MusicBot/tree/dev.svg?style=svg)](https://circleci.com/gh/BjoernPetersen/MusicBot/tree/dev)

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
  - [pyaudio](https://people.csail.mit.edu/hubert/pyaudio/)
  - [pylru](https://github.com/jlhutch/pylru)
  - [cryptography](https://github.com/pyca/cryptography)
  - If you want to be able to queue youtube songs
    - [pafy](https://github.com/mps-youtube/pafy)
    - [youtube-dl](https://github.com/rg3/youtube-dl)
  - If you want to be able to queue soundcloud songs
    - [soundcloud](https://github.com/soundcloud/soundcloud-python)
  - To use the app:
    - [hug](https://github.com/timothycrosley/hug)
    - [passlib](https://pypi.python.org/pypi/passlib)
    - [pyjwt](https://github.com/jpadilla/pyjwt)
    - [bcrypt](https://github.com/pyca/bcrypt) (or some other bcrypt library)
    - [aiohttp_wsgi](https://github.com/etianen/aiohttp-wsgi)
