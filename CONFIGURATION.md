option name | description | possible values | default value
----------- | ----------- | --------------- | -------------
gmusic_locale | the locale your gmusic account is registered in | "de_DE", "en_US" etc. or 0 for system default | 0
auto_updates | enables automatic updates from the master branch of this repo on startup | 0 or 1 | 0
load_plugins | load additional commands from the plugins folder | 0 or 1 |1
max_downloads | maximal simultaneous downloads. Choose lower values for slower internet connections. | any number greater than 0 | 1
max_conversions | maximal simultaneous audio file conversions. Choose lower values for slower CPUs | any number greater than 0 | 1
quality | the quality of songs downloaded from Google Play Music. Choose lower values if disk space is limited | "low", "med" or "hi" | "med"
secrets_location | the directory your "secrets.json" is located in | any path (relative or absolute) to a directory | ""
song_path | the directory all songs should be downloaded into | any path (relative or absolute) to a directory | "songs"
suggest_songs | enables suggestions from the BotStation if users send an empty inline query ("@yourbotname ") | 0 or 1 | 1
