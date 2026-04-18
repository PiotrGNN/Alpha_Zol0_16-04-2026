
# DEVELOPMENT.md – Dokumentacja developerska

**Uwaga: Od LEVEL-Ω cała logika decyzji, equity i logów została przeniesiona do bazy danych Postgres. API oraz worker komunikują się wyłącznie przez bazę – nie są już używane pliki CSV ani logi lokalne. Szczegóły: core/db_models.py, core/db_utils.py, api_status.py, core/BotCore.py.**


## Kluczowe strategie i technologie

- **Trend Following & Momentum** – klasyczne strategie podążania za trendem, pozwalające zyskom rosnąć w hossie.
- **Mean Reversion & Grid Trading** – strategie na konsolidacje, wielokrotne małe zyski z wahań.
- **Breakout** – szybka reakcja na wybicia i nagłe ruchy.
- **Sentiment/NLP AI** – analiza newsów, tweetów i nastrojów rynkowych (transformery, modele językowe, szybka reakcja na newsy).
- **Arbitraż & Market Making** – wykorzystywanie nieefektywności, zysk na spreadach, cross-exchange, HFT.
- **Reinforcement Learning (RL)** – adaptacyjne strategie AI, uczenie przez doświadczenie, dynamiczne dostosowanie polityki, integracja z federated learning.
- **Federated Learning** – rozproszona aktualizacja modeli AI, dzielenie wiedzy między instancjami, ciągłe doskonalenie.
- **DynamicStrategyRouter** – automatyczne przełączanie strategii w zależności od warunków rynkowych.

## Synergia i adaptacja

ZoL0 łączy klasyczne strategie, AI/ML, RL, federated learning i dynamiczne zarządzanie ryzykiem w jeden ekosystem. Bot uczy się z każdego trade’u, aktualizuje modele i parametry, dzieląc wiedzę między instancjami. Dzięki temu przewaga bota rośnie z czasem, a system adaptuje się do każdego typu rynku (hossa, bessa, konsolidacja, newsy, anomalie, wysokie VIX).

## Przykład użycia Reinforcement Learning (RL)

```python
from strategies.rl_omega import RLOmegaAgent
agent = RLOmegaAgent(state_dim=10, action_dim=3)
state = [0.1]*10
action = agent.act(state)
reward = 1.0
next_state = [0.2]*10
done = False
agent.remember(state, action, reward, next_state, done)
agent.replay()  # Uczy się na podstawie doświadczeń
```

## Przykład użycia Federated Learning

```python
# Załóżmy, że mamy kilka agentów RL na różnych maszynach:
local_weights = agent.get_weights_for_federation()
# ...zbierzemy je z innych instancji...
agent.aggregate_federated_weights([local_weights, other_weights1, other_weights2])
# Aktualizacja globalnej polityki
```

## Przykład użycia NLP/Sentiment

```python
from ai.sentiment_model import SentimentModel
model = SentimentModel()
score, label = model.predict("Bitcoin to the moon!")
```

## Przykład arbitrażu/market making

```python
# Pseudokod: wykrywanie różnicy cen na giełdach
price_a = fetch_price('BTCUSDT', exchange='A')
price_b = fetch_price('BTCUSDT', exchange='B')
if abs(price_a - price_b) > threshold:
    execute_arbitrage(price_a, price_b)
```


## Checklisty LEVEL0-5

Pełne checklisty i statusy znajdują się w plikach:
- [ZoL0-Level-0-5.md](ZoL0-Level-0-5.md)
- [AUDIT_STATUS.md](AUDIT_STATUS.md)
- [TODO.md](TODO.md)

## Przykłady użycia

### Uruchomienie bota
```sh
python main.py
```

### Przykład użycia modelu ML
```python
from models.trend_predictor import TrendPredictor
model = TrendPredictor()
trend = model.predict(ohlcv_data)
```

### Przykład testu jednostkowego
```sh
pytest tests/test_risk_manager.py
```

## Integracja z Bybit, FL, ZTA

- **Bybit**: MarketDataFetcher i OrderExecutor obsługują REST API Bybit (multi-symbol, retry, throttle).
- **Federated Learning (FL)**: Modele ML mogą być aktualizowane rozproszonymi wagami (patrz: fl/training.py, fl/runner.py).
- **ZTA (Zero Trust Architecture)**: Moduły security/zero_trust.py, autoryzacja tokenów, logowanie zdarzeń.


## Testy i coverage

Testy pokrywają wszystkie kluczowe moduły (MarketDataFetcher, OrderExecutor, RiskManager, AI, warstwy profit, bezpieczeństwo, federated learning). **Logi, decyzje i equity są testowane pod kątem poprawności zapisu do bazy Postgres.**

## Status LEVEL-Ω (2025-07-30)

- Wszystkie warstwy, modele, strategie i testy są produkcyjne i w pełni pokryte testami.
- Brak stubs, TODO, placeholderów w kodzie produkcyjnym.
- System gotowy do wdrożenia produkcyjnego.
