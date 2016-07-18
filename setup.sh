#!/bin/bash
if [[ $EUID -ne 0 ]]; then
  echo "You must be a root user" 2>&1
  exit 1
fi

apt-get install libav-tools libavcodec-extra-56 libssl-dev libffi-dev libasound2-dev -y
pip install python-telegram-bot gmusicapi youtube-dl pafy pydub simpleaudio soundcloud --upgrade
