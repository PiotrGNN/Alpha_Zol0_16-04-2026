from core.AutoHeal import AutoHeal


class DummyModel:
    def __init__(self):
        self.status = "ok"
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True


class DummyStrategy:
    def __init__(self):
        self.status = "ok"
        self.restarted = False

    def restart(self):
        self.restarted = True


def test_auto_heal():
    model = DummyModel()
    strategy = DummyStrategy()
    ah = AutoHeal()
    # No failure
    assert not ah.heal(model, strategy)
    # Simulate failure
    model.status = "error"
    strategy.status = "regression"
    assert ah.heal(model, strategy)
    assert model.rolled_back
    assert strategy.restarted
    assert ah.rollback_count == 1
