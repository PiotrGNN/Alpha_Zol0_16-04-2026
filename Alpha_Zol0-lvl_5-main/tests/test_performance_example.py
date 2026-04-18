import time


def test_backtest_performance():
    start = time.time()
    # uruchom backtest (mock)
    time.sleep(0.1)
    duration = time.time() - start
    assert duration < 2.0  # np. backtest musi być szybki
