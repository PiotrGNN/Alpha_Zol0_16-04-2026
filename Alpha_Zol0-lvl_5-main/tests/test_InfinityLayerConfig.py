import tempfile

from core.InfinityLayerConfig import InfinityLayerConfig


def test_infinity_layer_config():
    config = InfinityLayerConfig()
    config.set("param1", 42)
    assert config.get("param1") == 42
    with tempfile.NamedTemporaryFile(delete=False, mode="w+") as tmp:
        path = tmp.name
        config.save(path)
        config2 = InfinityLayerConfig(path)
        assert config2.get("param1") == 42
