import imp
import logging
import os

from colorama import Fore


plugin_dir = "./plugins"


class PluginLoader(object):
    plugins = []

    # Load all Plugins present in the plugin_dir directory
    def load_plugins(self):
        logger = logging.getLogger("musicbot")
        if not os.path.isdir(plugin_dir):
            return
        possible_plugins = os.listdir(plugin_dir)
        for filename in possible_plugins:
            if not os.path.isfile(os.path.join(plugin_dir, filename)):
                continue
            split = filename.split('.')
            if not (len(split) > 1 and split[-1] == "py"):
                continue
            name = "".join(split[:-1])
            module_info = imp.find_module(name, [plugin_dir])
            try:
                module = imp.load_module(name, *module_info)
                dir_list = dir(module)
                if ("get_label" in dir_list) and ("run_command" in dir_list):
                    self.plugins.append(module)
                else:
                    logger.error(Fore.RED + "'%s' is not a valid plugin!" + Fore.RESET, filename)
            except Exception as e:
                logger.error(Fore.RED + "%s error while loading plugin '%s': \n %s" + Fore.RESET,
                             type(e).__name__, filename, e)
            finally:
                module_info[0].close()

    # Return a list of loaded plugins
    def get_plugins(self):
        return self.plugins
