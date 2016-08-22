import json


def restore_blank_secrets():
    print("Restoring empty secrets")
    try:
        with open("config/secrets.json", 'r') as secrets_file:
            secrets = json.loads(secrets_file.read())
            secrets_keys = secrets.keys()
    except IOError:
        return

    secrets = {}
    for key in secrets_keys:
        secrets[key] = ""

    with open("config/secrets.json", 'w') as secrets_file:
        secrets_file.write(json.dumps(secrets))


if __name__ == '__main__':
    restore_blank_secrets()