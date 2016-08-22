import json
import os


def save_secrets():
    with open("config/secrets.json", 'r') as secrets_file:
        secrets = json.loads(secrets_file.read())
        secrets_keys = secrets.keys()

    print("Reading secrets from environment variables")
    secrets = {}
    for key in secrets_keys:
        secrets[key] = os.environ[key]

    print("Writing secrets to secrets.json")
    with open("config/secrets.json", 'w') as secrets_file:
        secrets_file.write(json.dumps(secrets))

if __name__ == '__main__':
    save_secrets()
