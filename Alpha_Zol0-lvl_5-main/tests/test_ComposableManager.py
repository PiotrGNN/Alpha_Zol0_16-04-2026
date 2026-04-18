from core.ComposableManager import ComposableManager


def dummy_module_1(*args, **kwargs):
    return "mod1"


def dummy_module_2(*args, **kwargs):
    return "mod2"


def test_composable_manager():
    cm = ComposableManager()
    cm.register_module("m1", dummy_module_1)
    cm.register_module("m2", dummy_module_2)
    cm.activate("m1")
    cm.activate("m2")
    results = cm.run_active()
    assert results["m1"] == "mod1"
    assert results["m2"] == "mod2"
    cm.deactivate("m1")
    results = cm.run_active()
    assert "m1" not in results
    assert "m2" in results
