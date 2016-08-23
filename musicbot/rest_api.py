import asyncio
import json
import logging
import os
import threading
import uuid

import falcon
import hug
import jwt
from passlib.hash import bcrypt_sha256

from musicbot.music_apis import Song, AbstractSongProvider, AbstractAPI


class _API(object):
    '''
    Represents an API
    '''

    def __init__(self, api):
        if not isinstance(api, AbstractAPI):
            raise ValueError("Not an AbstractAPI implementation")

        self.api = api
        self.api_pretty_name = api.get_pretty_name()
        self.api_name = self.api.get_name()
        self.is_song_provider = isinstance(api, AbstractSongProvider)

    def to_json(self):
        return {"api_name": self.api_name,
                "is_song_provider": self.is_song_provider,
                "api_pretty_name": self.api_pretty_name}

    @staticmethod
    def from_json(api_json):
        try:
            api_name = api_json['api_name']
        except KeyError:
            raise ValueError("Invalid JSON. Missing key: 'api_name'")

        try:
            api = music_api_names[api_name]
        except KeyError:
            raise ValueError("Unknown API: " + api_name)

        return _API(api)

    def __eq__(self, other):
        if not isinstance(other, _API):
            return False
        return self.api_name == other.api_name

    def __hash__(self):
        return hash(self.api_name)


class _SecretClient(object):

    def __init__(self, name, pw_hash, permissions):
        self.name = name
        self.pw_hash = pw_hash
        self.permissions = permissions

    def __str__(self):
        return self.name

    def __eq__(self, other):
        if not isinstance(other, _SecretClient):
            return False
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.name)

    def to_json(self):
        return {"name": self.name,
                "permissions": self.permissions,
                "pw_hash": self.pw_hash}

    @staticmethod
    def from_json(client_json):
        try:
            name = client_json['name']
            pw_hash = client_json['pw_hash']
            permissions = client_json['permissions']
            return _SecretClient(name, pw_hash, permissions)
        except KeyError as e:
            raise ValueError("Missing key: " + str(e))


def _create_token(secrets):
    '''
    Create a string token, write it to secrets['token'] and return it.
    '''
    token = str(uuid.uuid4())
    secrets['token'] = token
    return token


def _read_secrets():
    path = "config/rest_secrets.json"
    if not os.path.isfile(path):
        empty_secrets = {"token": "", "clients": []}
        token = _create_token(empty_secrets)
        with open(path, 'w') as secrets_file:
            secrets_file.write(json.dumps(empty_secrets))
        return token, dict(), set()
    with open(path, 'r') as secrets_file:
        secrets = json.loads(secrets_file.read())
        token = secrets['token']
        json_clients = secrets['clients']
        client_list = map(_SecretClient.from_json, json_clients)
        clients = {}
        client_names = set()
        for client in client_list:
            clients[client.name] = client
            client_names.add(client.name)
        return token, clients, client_names


def _add_client(client):
    with _add_client_lock:
        clients[client.name] = client
        client_names.add(client.name)
        secrets_json = {"token": token, "clients": list(map(_SecretClient.to_json, clients.values()))}
        with open("config/rest_secrets.json", 'w') as secrets_file:
            secrets_file.write(json.dumps(secrets_json))


_add_client_lock = threading.Lock()
player = None
music_api_names = {}
apis_json = []
token, clients, client_names = _read_secrets()

logger = logging.getLogger("musicbot")


def init(music_apis, queued_player):
    '''
    Keyword arguments:
    music_apis -- a list of AbstractAPIs
    queued_player -- a Player instance
    '''
    global music_api_names
    global apis_json
    global player
    global queue
    music_api_names = {api.get_name(): api for api in music_apis}
    apis_json = list(map(lambda music_api: _API(music_api).to_json(), music_apis))
    player = queued_player
    queue = player.get_queue()


def verify(user_token):
    try:
        return jwt.decode(user_token, token, algorithm="HS256")
    except (KeyError, jwt.InvalidTokenError):
        return False

authentication = hug.authentication.token(verify)


@hug.post()
def register(username, password, response=None):
    if not username or not username.strip():
        response.status = falcon.HTTP_BAD_REQUEST
        return "Empty username"
    if username in client_names:
        response.status = falcon.HTTP_CONFLICT
        return "Name already in use"

    if len(password.strip()) < 6:
        response.status = falcon.HTTP_BAD_REQUEST
        return "Invalid password. Must be of length >= 6"
    pw_hash = bcrypt_sha256.encrypt(password)
    client = _SecretClient(username, pw_hash, ["user"])
    _add_client(client)
    user_token = {
        "permissions": client.permissions
    }
    return jwt.encode(user_token, token, algorithm="HS256")


@hug.put()
def login(username, password, response=None):
    if username not in client_names:
        response.status = falcon.HTTP_400
        return "unknown"
    client = clients[username]
    success = bcrypt_sha256.verify(password, client.pw_hash)
    if not success:
        response.status = falcon.HTTP_400
        return "wrong password"
    user_token = {
        "permissions": client.permissions
    }
    return jwt.encode(user_token, token, algorithm="HS256")


@hug.get()
def music_apis():
    return apis_json


@asyncio.coroutine
@hug.put(requires=authentication)
def queue(body, remove: hug.types.boolean=False, response=None):
    try:
        song = Song.from_json(body, music_api_names)
    except ValueError as e:
        response.status = falcon.HTTP_400
        return str(e)

    if remove:
        try:
            queue.remove(song)
        except ValueError as e:
            response.status = falcon.HTTP_400
            return "song {} is not in queue".format(song)
    else:
        queue.append(song)
    return "OK"


@asyncio.coroutine
@hug.get()
def suggestions(api_name, max_fetch: hug.types.number=10, response=None):
    max_fetch = min(10, max(1, max_fetch))

    try:
        api = music_api_names[api_name]
    except KeyError:
        response.status = falcon.HTTP_400
        return "Unknown API"

    if isinstance(api, AbstractSongProvider):
        return list(map(Song.to_json, api.get_suggestions(max_fetch)))
    else:
        response.status = falcon.HTTP_400
        return []


@asyncio.coroutine
@hug.get()
def search(api_name, query, max_fetch: hug.types.number=50, response=None):
    max_fetch = min(50, max(1, max_fetch))
    try:
        api = music_api_names[api_name]
    except KeyError:
        response.status = falcon.HTTP_400
        return "Unknown API"

    if not query:
        response.status = falcon.HTTP_400
        return "Invalid query"

    return list(map(Song.to_json, api.search_song(query, max_fetch=max_fetch)))


@hug.get()
def player_state():
    current_song = player.get_current_song()
    if current_song:
        song_json = current_song.to_json()
    else:
        song_json = None

    return {"current_song": song_json,
            "queue": list(map(Song.to_json, queue)),
            "paused": player._pause}


@hug.put(requires=authentication)
def toggle_pause():
    if player._pause:
        player.resume()
    else:
        player.pause()
    return player_state()


@asyncio.coroutine
@hug.put(requires=authentication)
def next_song():
    player.next()
    return player_state()


@asyncio.coroutine
@hug.put(requires=authentication)
def move(moving_song_json, other_song_json, after_other: hug.types.boolean=False, response=None):
    try:
        moving_song = Song.from_json(moving_song_json, music_api_names)
        other_song = Song.from_json(other_song_json, music_api_names)
    except ValueError as e:
        response.status = falcon.HTTP_400
        return str(e)

    try:
        queue.remove(moving_song)
    except ValueError:
        response.status = falcon.HTTP_400
        return "song {} is not in queue".format(moving_song)

    try:
        index = queue.index(other_song)
        if after_other:
            index += 1
        queue.insert(index, moving_song)
        return player_state()
    except ValueError:
        response.status = falcon.HTTP_400
        return "song {} is not in queue".format(other_song)
