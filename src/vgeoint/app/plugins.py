"""Replacement for the C++ BPlugins (QPluginLoader + *Plugin.dll).

Python plugins register under the "vgeoint.bplugins" entry-point group and expose a QDialog subclass
implementing the BPluginInterface contract: name(), vn_name(), get_icon(), auto_add_output_files(),
output_files(), output_data_type(), set_map_canvas(), set_layer_tree_view(), show(), and a `complete`
signal. Plugin key prefixes keep their meaning: V_ = Vector menu, R_ = Raster menu, T_ = Tool menu.
"""

import logging
from importlib.metadata import entry_points

log = logging.getLogger(__name__)

RASTER = 0
VECTOR = 1


def load_plugins(parent) -> dict:
    """Return {plugin_name: plugin_instance}."""
    plugins = {}
    for ep in entry_points(group="vgeoint.bplugins"):
        try:
            plugin = ep.load()(parent)
        except Exception:  # noqa: BLE001 - a broken plugin must not stop the app
            log.exception("Cannot load plugin %s", ep.name)
            continue
        plugins[plugin.name()] = plugin
    return plugins
