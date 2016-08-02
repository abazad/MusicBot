import imp
import os

plugin_dir = "./plugins"


class PluginLoader(object):
    plugins = []

    # Load all Plugins present in the plugin_dir directory
    def load_plugins(self):
        possible_plugins = os.listdir(plugin_dir)
        for filename in possible_plugins:
            split = filename.split('.')
            if not (len(split) > 1 and split[-1] == "py"):
                continue
            name = "".join(split[:-1])
            module_info = imp.find_module(name, [plugin_dir])
            try:
                module = imp.load_module(name, *module_info)
                if ("get_label" in dir(module)) and ("run_command" in dir(module)):
                    self.plugins.append(module)
                else:
                    print("\033[0;31m'%s' is not a valid plugin!\033[0m" % filename)
            except Exception as e:
                print("\033[0;31m%s error while loading plugin '%s': \n %s\033[0m" % (type(e).__name__, filename, e))
            finally:
                module_info[0].close()

    # Return a list of loaded plugins
    def get_plugins(self):
        return self.plugins
