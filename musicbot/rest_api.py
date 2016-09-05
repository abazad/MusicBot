import asyncio
import json
import logging
import os
import sqlite3
import threading
import uuid

import falcon
import hug
import jwt
from passlib.hash import bcrypt_sha256
from pylru import lrudecorator

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


class _Permission(object):
    def __init__(self, name, description):
        self.name = name
        self.description = description

    def to_json(self):
        return {
            "name": self.name,
            "description": self.description
        }

    @staticmethod
    def from_json(perm_json):
        try:
            name = perm_json['name']
            description = perm_json['description']
        except KeyError:
            return ValueError("Missing key in json")
        return _Permission(name, description)


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


def _create_user_token(username, permissions):
    """
    Creates an encoded user token.
    :param username: the username
    :param permissions: a list of permissions (strings)
    :return: the encoded token
    """
    user_token = {
        "name": username,
        "permissions": permissions
    }
    return jwt.encode(user_token, token, algorithm="HS256")


def _read_secrets(secrets_password):
    path = "config/rest_bot.secrets"
    if not os.path.isfile(path):
        empty_secrets = {"token": ""}
        _create_token(empty_secrets)
        encoded_token = jwt.encode(empty_secrets, secrets_password, algorithm="HS256")
        with open(path, 'wb') as secrets_file:
            secrets_file.write(encoded_token)
        return encoded_token
    with open(path, 'rb') as secrets_file:
        secrets_content = secrets_file.read()
        secrets = jwt.decode(secrets_content, secrets_password, algorithm="HS256")
        token = secrets['token']
        return token


def _get_db_conn():
    return sqlite3.connect("config/clients.db")


@lrudecorator(256)
def _get_client(username):
    with _get_db_conn() as db:
        cursor = db.cursor()
        cursor.execute("SELECT pw_hash, permissions FROM clients WHERE username=?", [username])
        client_row = cursor.fetchone()
        if not client_row:
            return None
        pw_hash = client_row[0]
        permissions = client_row[1].split(",")
        return _SecretClient(username, pw_hash, permissions)


def _add_client(client):
    with _add_client_lock:
        if _get_client(client.name):
            raise ValueError("client already in clients")
        with _get_db_conn() as db:
            db.execute("INSERT INTO clients(username, pw_hash, permissions) VALUES(?, ?, ?)",
                       (client.name,
                        client.pw_hash,
                        ",".join(client.permissions)))


available_permissions = [
    _Permission("mod", "all admin permissions, except exit, reset and granting permissions"),
    _Permission("queue_remove", "remove a song from the queue"),
    _Permission("exit", "shut the bot down"),
    _Permission("reset", "reset all bot settings, delete the remote playlist and shut the program down")
]

_add_client_lock = threading.Lock()
player = None
queue = []
music_api_names = {}
apis_json = []
token = None

logger = logging.getLogger("musicbot")

with _get_db_conn() as db:
    db.execute(
        "CREATE TABLE IF NOT EXISTS clients (userid INTEGER PRIMARY KEY ASC AUTOINCREMENT, username TEXT UNIQUE NOT NULL, pw_hash CHAR(75) NOT NULL, permissions TEXT)")

with open("config/config.json", 'r') as config_file:
    config = json.loads(config_file.read())
    allow_rest_admin = config.get("allow_rest_admin", True)


def init(music_apis, queued_player, secrets_password):
    """
    Keyword arguments:
    music_apis -- a list of AbstractAPIs
    queued_player -- a Player instance
    """
    global music_api_names
    global apis_json
    global player
    global queue
    global token
    music_api_names = {api.get_name(): api for api in music_apis}
    apis_json = list(map(lambda music_api: _API(music_api).to_json(), music_apis))
    player = queued_player
    queue = player.get_queue()
    try:
        token = _read_secrets(secrets_password)
    except jwt.InvalidTokenError:
        raise ValueError("Invalid password")


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
    username = username.strip().lower()
    if len(username) > 64:
        response.status = falcon.HTTP_UNPROCESSABLE_ENTITY
        return "Username too long"
    if _get_client(username):
        response.status = falcon.HTTP_CONFLICT
        return "Name already in use"

    if len(password.strip()) < 6:
        response.status = falcon.HTTP_BAD_REQUEST
        return "Invalid password. Must be of length >= 6"
    pw_hash = bcrypt_sha256.encrypt(password)
    client = _SecretClient(username, pw_hash, ["user"])
    try:
        _add_client(client)
    except ValueError:
        response.status = falcon.HTTP_CONFLICT
        return "Name already in use"
    return _create_user_token(username, client.permissions)


@hug.put()
def login(username, password, response=None):
    """
    Logs user in. Returns status 400 response if user doesn't exist or password is wrong.
    :param username: a username
    :param password: a password
    :return: a token to authenticate with
    """
    if not username or not username.strip():
        response.status = falcon.HTTP_400
        return "empty username"
    username = username.strip().lower()
    client = _get_client(username)
    if not client:
        response.status = falcon.HTTP_400
        return "unknown"
    success = bcrypt_sha256.verify(password, client.pw_hash)
    if not success:
        response.status = falcon.HTTP_400
        return "wrong password"
    return _create_user_token(username, client.permissions)


@hug.get()
def music_apis():
    return apis_json


@asyncio.coroutine
@hug.put(requires=authentication)
def queue(body, remove: hug.types.boolean = False, user: hug.directives.user = None, response=None):
    try:
        song = Song.from_json(body, music_api_names)
    except ValueError as e:
        response.status = falcon.HTTP_400
        return str(e)

    if remove:
        if not has_permission(user, ["admin", "mod", "queue_remove"]):
            response.status = falcon.HTTP_FORBIDDEN
            return "Not permitted"
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
def suggestions(api_name, max_fetch: hug.types.number = 10, response=None):
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
def search(api_name, query, max_fetch: hug.types.number = 50, response=None):
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


@hug.local()
@hug.get()
def player_state():
    current_song = player.get_current_song()
    if current_song:
        song_json = current_song.to_json()
    else:
        song_json = None

    return {"current_song": song_json,
            "last_played": list(map(Song.to_json, player.get_last_played())),
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
def move(moving_song_json, other_song_json, after_other: hug.types.boolean = False, response=None):
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


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def has_admin(user: hug.directives.user=None):
    """
    Check whether the server has an admin.
    If there is none and none is allowed, also returns True.
    :return: True or False
    """
    if not allow_rest_admin:
        return True
    if user and ("admin" in user['permissions']):
        return True
    with _get_db_conn() as db:
        cursor = db.cursor()
        cursor.execute("SELECT permissions FROM clients")
        rows = cursor.fetchall()
        for row in rows:
            if "admin" in row[0].split(","):
                return True
        return False


@hug.local()
@hug.get(requires=authentication)
def is_admin(user: hug.directives.user):
    """
    Check whether the the calling user is admin
    :return: True or False
    """
    return "admin" in user['permissions']


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def has_permission(user: hug.directives.user, needed_permissions=["admin"]):
    """
    Ensure that a user has at least one of the needed permissions.
    :param needed_permissions: an iterable of permission strings
    :return: True or False
    """
    return not set(user['permissions']).isdisjoint(set(needed_permissions))


@asyncio.coroutine
@hug.get(requires=authentication)
def get_permissions(user: hug.directives.user):
    """
    Return the permissions of the client.
    :return: a list of permissions
    """
    return user['permissions']


claim_admin_lock = threading.Lock()


@asyncio.coroutine
@hug.get(requires=authentication)
def claim_admin(user: hug.directives.user, response=None):
    """
    Request admin rights. If allow_rest_admin is set in config and no other admin exists, return admin token.
    :return: an admin token on success.
    """
    username = user['name']
    permissions = user['permissions']
    if "admin" in permissions:
        response.status = falcon.HTTP_400
        return None
    with claim_admin_lock:
        if has_admin():
            response.status = falcon.HTTP_CONFLICT
            return None
        permissions.append("admin")
        permissions = list(set(permissions))
        with _get_db_conn() as db:
            db.execute("UPDATE clients SET permissions=? WHERE username=?", (",".join(permissions), username))
    return _create_user_token(username, permissions)


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def get_available_permissions(user: hug.directives.user=None, response=None):
    """
    Return a list of available permissions an admin can grant to users.
    Needs admin permission.
    :return: a list of permissions
    """
    if user and (not is_admin(user)):
        response.status = falcon.HTTP_FORBIDDEN
        return None
    return available_permissions


@hug.local()
@asyncio.coroutine
@hug.get(requires=authentication)
def get_users(user: hug.directives.user=None, response=None):
    """
    Return a list of all registered users with their permissions.
    Needs admin permission.
    :return: a list of users or None
    """
    if user and (not is_admin(user)):
        response.status = falcon.HTTP_FORBIDDEN
        return None
    with _get_db_conn() as db:
        cursor = db.cursor()
        cursor.execute("SELECT username, permissions FROM clients")
        result = []
        for row in cursor.fetchall():
            result.append({
                "username": row[0],
                "permissions": row[1].split(",")
            })
        return result


@asyncio.coroutine
@hug.put(requires=authentication)
def grant_permission(target_username, permission: hug.types.json, user: hug.directives.user = None, response=None):
    """
    Grant a permission to a user
    Note that the new permissions only apply after the user logged out and in again.
    Needs admin permission.
    :param target_username: the username of the user the permission should be granted
    :param permission: the permission as returned by get_permissions
    :return: 'OK', error message or None
    """
    if not is_admin(user):
        response.status = falcon.HTTP_FORBIDDEN
        return None
    target_username = target_username.strip().lower()
    client = _get_client(target_username)
    if not client:
        response.status = falcon.HTTP_400
        return "unknown target user"
    permissions = client.permissions
    permissions.append(permission)
    permissions = list(set(permissions))
    with _get_db_conn() as db:
        db.execute("UPDATE clients SET permissions=? WHERE username=?", [",".join(permissions), target_username])
    return "OK"


@asyncio.coroutine
@hug.put(requires=authentication)
def revoke_permission(target_username, permission: hug.types.json, user: hug.directives.user = None, response=None):
    """
    Revokes a granted permission.
    Note that the new permissions only apply after the user logged out and in again.
    Needs admin permission.
    :param target_username: the username of the user whos permission should be revoked
    :param permission: the permission as returned by get_permissions
    :return: 'OK' or error_message or None
    """
    if not is_admin(user):
        response.status = falcon.HTTP_FORBIDDEN
        return None
    target_username = target_username.strip().lower()
    client = _get_client(target_username)
    if not client:
        response.status = falcon.HTTP_400
        return "unknown target user"
    permissions = client.permissions
    try:
        permissions.remove(permission)
    except ValueError:
        pass
    with _get_db_conn() as db:
        db.execute("UPDATE clients SET permissions=? WHERE username=?", [",".join(permissions), target_username])
    return "OK"
