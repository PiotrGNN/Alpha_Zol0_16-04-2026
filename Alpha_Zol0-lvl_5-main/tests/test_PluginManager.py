from core.PluginManager import PluginManager


def dummy_plugin(*args, **kwargs):
    return "plugin_called"


def test_plugin_manager():
    pm = PluginManager()
    pm.register_plugin("test", dummy_plugin)
    assert pm.load_plugin("test") == dummy_plugin
    result = pm.call_plugin("test")
    assert result == "plugin_called"
    assert pm.load_plugin("notfound") is None
    assert pm.call_plugin("notfound") is None
