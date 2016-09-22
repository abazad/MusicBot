from musicbot import config


def show_secrets_keys():
    secrets = config.get_secrets()
    keys = list(secrets)

    result = {}
    out = ""
    for i in range(0, len(keys)):
        key = keys[i]
        result[str(i)] = key
        out += "(" + str(i) + ") " + key + "\n"

    print("Available secrets: \n" + out)
    return result


if __name__ == "__main__":
    more = True
    while more:
        indices = show_secrets_keys()
        choice = input("Which secret should be invalidated? ").strip()
        if choice in indices:
            key = indices[choice]
            del config.get_secrets()[key]
            config.save_secrets()
        else:
            print("Invalid index")
        more = (input("Invalidate another secret (Y/N)?").lower() == "y")
