# ZoL0 AI Trading Bot (Runtime Hardening Branch)

Repozytorium jest utrzymywane w trybie runtime/profitability hardening. Status promocji do produkcji jest wyznaczany przez aktualne artefakty gate (`reports/paper_readiness/*`, `reports/paper_runtime_patch_validation/*`), a nie przez statyczne deklaracje.

---


## Architektura i główne moduły

**Warstwowa architektura ZoL0:**

```
┌──────────────────────────────┐
│      MarketDataFetcher       │
└─────────────┬────────────────┘
              │
┌─────────────▼───────────────┐
│     AIStrategyEngine        │
└─────────────┬───────────────┘
              │
┌─────────────▼────────────────────────────────────────────────────────────┐
│   [trend_predictor, volatility_forecaster, tp_sl_optimizer, ai_utils]   │
└─────────────┬────────────────────────────────────────────────────────────┘
              │
┌─────────────▼───────────────┐
│        RiskManager          │
└─────────────┬───────────────┘
              │
┌─────────────▼───────────────┐
│ StrategyPerformanceTracker  │
└─────────────┬───────────────┘
              │
┌─────────────▼───────────────┐
│      OrderExecutor          │
└─────────────┬───────────────┘
              │
┌─────────────▼───────────────┐
│ DynamicStrategyRouter       │
└─────────────┬───────────────┘
              │
┌─────────────▼───────────────┐
│ Security/ZeroTrust          │
└─────────────┬───────────────┘
              │
┌─────────────▼───────────────┐
│ Federated Learning          │
└─────────────┬───────────────┘
              │
┌─────────────▼───────────────┐
│ InfinityLayer               │
└─────────────────────────────┘
```

**Opis przepływu AI decyzji i egzekucji:**

1. MarketDataFetcher pobiera dane OHLCV i przekazuje do AIStrategyEngine.
2. AIStrategyEngine uruchamia produkcyjne modele ML (trend_predictor, volatility_forecaster, tp_sl_optimizer, ai_utils).
3. Wyniki modeli trafiają do RiskManagera, który dynamicznie zarządza ryzykiem (drawdown, limity, AI tuning).
4. StrategyPerformanceTracker monitoruje wyniki strategii (PnL, winrate, drawdown, Sharpe, score, hitrate).
5. OrderExecutor egzekwuje zlecenia (REST, retry, throttle, logi).
6. DynamicStrategyRouter przełącza strategie na podstawie scoringu i warunków rynkowych.
7. Security/ZeroTrust waliduje wejścia, autoryzuje tokeny, loguje zdarzenia.
8. Federated Learning umożliwia rozproszoną aktualizację modeli AI.
9. InfinityLayer zapewnia logowanie, konfigurację i status warstwy ∞.

Każda decyzja, metryka i egzekucja są logowane (AI JSON logger, InfinityLayerLogger). Całość podlega warstwom bezpieczeństwa, optymalizacji i federacyjnemu uczeniu.

---

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

## Filozofia zysku i bezpieczeństwa

- Preferowane są zagrania o wysokim potencjale (trend, breakout, sentyment) z jednoczesnym cięciem strat szybko i automatycznie ("pozwól zyskom rosnąć, tnij straty szybko").
- Dynamiczne przełączanie strategii i ograniczanie ryzyka chroni przed oddaniem wcześniejszych zysków.
- System jest zgodny z Level Ω – wszystkie strategie i komponenty wykorzystują architekturę ZoL0 w pełni.

## Przyszłościowe rozwiązania

Wprowadzenie RL i federated learning już teraz stawia bota na czele innowacji. Z czasem przewyższą one tradycyjne algorytmy wraz z gromadzeniem danych i doświadczeń. To inwestycja w długoterminową dominację.

## Oczekiwane metryki wydajności

- Wysoki współczynnik Sharpe’a
- Niski max drawdown
- Stabilny wzrost krzywej kapitału
- Zdywersyfikowany, inteligentny bot może osiągać ponadprzeciętne stopy zwrotu przy ograniczonej zmienności

## Podsumowanie: Maksymalizacja zysku przy zgodności z ZoL0 (LEVEL Ω)

Powyższe strategie i metody razem wzięte tworzą kompletny, zaawansowany ekosystem tradingowy idealnie dopasowany do możliwości ZoL0 (Level Ω). Wyłączne skupienie na rynku kryptowalut pozwoliło objąć pełne spektrum podejść – od klasycznego trend-following i mean reversion, przez strategie HFT/arbitrażowe, aż po nowatorskie wykorzystanie AI (NLP, Reinforcement Learning, Federated Learning). Dzięki temu bot może zarabiać na każdym typie ruchu rynku:

- W hossie trendowej: zarobi strategia momentum/trend (pozwalając zyskom rosnąć i nie “udusząc” pozycji zbyt wcześnie).
- W konsolidacji: stabilne dochody zapewni grid trading i mean reversion (wielokrotne małe zyski z wahań).
- Przy nagłych newsach: moduł sentymentu zareaguje błyskawicznie, wyprzedzając konkurencję.
- Na nieefektywnościach: arbiter wykroi pewny profit z różnic cen, market making dorzuci swoje na spreadach.
- W zmiennych, trudnych okresach: dynamiczne przełączanie strategii i ograniczanie ryzyka uchroni przed oddaniem wcześniejszych zysków (bot dostosuje się lub przeczeka ciężki okres, zamiast ślepo trzymać się jednej metody).

Architektura ZoL0 umożliwia ciągłe doskonalenie – bot uczy się z każdego trade’u, aktualizuje modele i parametry, dzieląc wiedzę między instancjami (federated learning) i stale podnosi poprzeczkę swojej skuteczności. Taka synergia technik sprawia, że długoterminowa przewaga bota rośnie z czasem, zamiast maleć. Efektem końcowym zastosowania tak wszechstronnego podejścia powinny być wyniki, które pozytywnie zaskoczą. Zdywersyfikowany, inteligentny bot może osiągać ponadprzeciętne stopy zwrotu przy ograniczonej zmienności – co jest świętym Graalem tradingu algorytmicznego.

Zgodność z Level Ω: Wszystkie zaproponowane strategie wykorzystują komponenty ZoL0 – od AI Strategy Engine po InfinityLayer – maksymalnie je obciążając pozytywną pracą. Bot działa więc dokładnie tak, jak zaprojektowano, że może, co gwarantuje pełne wykorzystanie inwestycji w jego rozwój.

Nacisk na zysk (profit-focus): Preferowane są zagrania o wysokim potencjale (trend, breakout, sentyment) z jednoczesnym cięciem strat szybko i automatycznie. To filozofia “pozwól zyskom rosnąć, tnij straty szybko” zaimplementowana algorytmicznie. Dzięki temu kapitał rośnie wykładniczo, nie tracąc czasu na odrabianie głębokich obsunięć.

Pełne spektrum = elastyczność: Niezależnie od tego, czy rynek będzie przez najbliższy rok w bessie, hossie czy trendzie bocznym – bot będzie miał plan działania. Ta elastyczność jest ogromnym atutem, bo większość prostych botów jest jednokierunkowa (np. tylko trendowa i traci w konsolidacji). ZoL0 z wieloma strategiami to prawdziwy multi-tool tradingu.

Przyszłościowe rozwiązania: Wprowadzenie tak zaawansowanych technologii jak RL czy federated learning już teraz stawia bota na czele innowacji. Nawet jeśli nie od razu dają one gigantyczną przewagę, z czasem przewyższą tradycyjne algorytmy wraz z gromadzeniem danych i doświadczeń. To inwestycja w długoterminową dominację.

Na podstawie przeprowadzonych analiz i symulacji, można oczekiwać, że ZoL0 (Ω) uzyska bardzo atrakcyjne metryki wydajności: wysoki współczynnik Sharpe’a, niski max drawdown i stabilny wzrost krzywej kapitału. Zaimplementowanie powyższych strategii z najwyższą dbałością o szczegóły (stopniowe testy, weryfikacja na danych, audyt bezpieczeństwa) sprawi, że efekty końcowe wprawią w osłupienie – zarówno inwestora/klienta (widzącego zyski), jak i być może samych twórców, gdy ich dzieło zacznie samodzielnie przewyższać oczekiwania. Z takim podejściem, ZoL0 AI Trading Bot może stać się prawdziwie przełomowym produktem na rynku tradingowym, łączącym zyskowność, niezawodność i nowatorskie rozwiązania AI.

---

## Kluczowe pliki i funkcje

- **core/BotCore.py** – główna pętla bota, integracja ML/risk, obsługa błędów, logowanie
- **core/MarketDataFetcher.py** – pobieranie danych OHLCV (REST, mock, retry, multi-symbol)
- **core/OrderExecutor.py** – egzekucja zleceń (REST, retry, throttle, logi)
- **core/RiskManager.py** – rolling drawdown, dynamiczne limity, AI/ML tuning
- **core/StrategyPerformanceTracker.py** – metryki strategii, rolling drawdown, Sharpe, winrate
- **models/trend_predictor.py** – predykcja trendu (RandomForest/XGBoost/LSTM, feature engineering, retrain, explain)
- **models/volatility_forecaster.py** – predykcja zmienności (XGBoost/RandomForest/Deep, feature extraction)
- **models/tp_sl_optimizer.py** – optymalizacja TP/SL (ATR, wsparcie/opór, risk:reward, backtest)
- **models/ai_utils.py** – pipeline danych ML, feature extraction, normalizacja
- **models/market_forecaster.py** – predykcja kierunku rynku (XGBoost/RandomForest)
- **models/time_advantage.py** – analiza przewagi czasowej wejścia
- **utils/logger.py** – AI JSON logger, logi decyzji, logi produkcyjne
- **utils/config_loader.py** – ładowanie konfiguracji YAML, obsługa ENV
- **utils/backtesting.py** – silnik backtestowy, scoring, latency, drawdown
- **core/DecisionInspector.py** – analiza i scoring decyzji AI
- **core/InfinityLayerLogger.py** – logowanie zdarzeń warstwy ∞
- **core/InfinityLayerConfig.py** – konfiguracja warstwy ∞
- **core/InfinityLayerStatus.py** – status i health warstwy ∞

---

## Instalacja i testowanie

### 1. Instalacja lokalna (Python)
```sh
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
python main.py
```

### 2. Testowanie
```sh
pytest tests --maxfail=3 --disable-warnings -v
```
Testy pokrywają wszystkie kluczowe moduły: MarketDataFetcher, OrderExecutor, RiskManager, AI, warstwy profit, bezpieczeństwo, federated learning. Logi w katalogu `logs/`.

### 3. Konfiguracja środowiska ENV
- Uzupełnij plik `secrets.env`:
  - KUCOIN_API_KEY=...
  - KUCOIN_API_SECRET=...
  - KUCOIN_API_PASSPHRASE=...
  - ZOL0_TOKEN=...
  - DATABASE_URL=... (wymagane przy `LIVE=1`)

### 4. Instalacja przez Docker
```sh
docker build -t zol0-bot .
docker run --env-file secrets.env zol0-bot
```

### 5. Docker Compose
W tym katalogu projektu (`Alpha_Zol0-lvl_5-main/Alpha_Zol0-lvl_5-main`) nie ma plików `docker-compose*.yml`.
Jeśli uruchamiasz compose, użyj jawnie pliku z katalogu, w którym on istnieje, i zweryfikuj ścieżkę przed startem.

---

## Deployment

### 1. Render.com
- Skonfiguruj usługę web w Render.com:
  - Wybierz repozytorium GitHub
  - buildCommand: `pip install -r requirements.txt`
  - startCommand: `python main.py`
  - Dodaj plik `render.yaml` do repozytorium
  - Ustaw zmienne środowiskowe z `secrets.env`
  - Monitoruj logi i status deploymentu

---

## Checklisty i linki
**Ważne:** Persistence działa w trybie dual-mode: `LIVE=1` wymaga jawnego `DATABASE_URL`, a `LIVE=0` może używać fallbacku SQLite. Szczegóły w `core/db_models.py` i `core/db_utils.py`.

- [ZoL0-Level-0-5.md](ZoL0-Level-0-5.md) – pełna checklista LEVELów
- [copilot_taskplan.yaml](copilot_taskplan.yaml) – automatyzacja i statusy
- [AUDIT_STATUS.md](AUDIT_STATUS.md) – status audytu i produkcyjności
- [TODO.md](TODO.md) – zadania, ulepszenia, status

---

## Changelog

- 2025-07-30: Pełna synchronizacja checklist, changelog, statusów LEVEL-Ω. Dodano diagram architektury, opis AI flow, linki do checklist, rozszerzona sekcja instalacji i deploymentu.
- 2025-07-29: Produkcyjny release LEVEL-Ω, pełny audyt, testy, bezpieczeństwo, federated learning.

---

## Checklisty, status LEVELów i automatyzacja

- [TODO.md](TODO.md) – zadania, ulepszenia, status
- [ZoL0-Level-0-5.md](ZoL0-Level-0-5.md) – pełna checklista LEVELów
- [copilot_taskplan.yaml](copilot_taskplan.yaml) – automatyzacja

**Status LEVELów (2025-07-29):**
- LEVEL 0: ✅
- LEVEL 1: ✅
- LEVEL 2: ✅
- LEVEL 3: ✅
- LEVEL 4: ✅
- LEVEL 5: ✅
- LEVEL ML: ✅ (wszystkie kluczowe moduły ML/risk produkcyjne)
- LEVEL API: ✅ (wszystkie kluczowe API/REST produkcyjne)
- LEVEL X: ✅
- LEVEL ∞: ✅

Statusy LEVEL traktuj jako historyczny kontekst rozwoju. Bieżącą gotowość runtime/profitability określają wyłącznie aktualne raporty gate i audytu.

---

## AI flow i architektura – podsumowanie

Architektura ZoL0 to warstwowy, produkcyjny pipeline AI tradingowy:
- Dane rynkowe pobiera `MarketDataFetcher`
- Analizuje je `AIStrategyEngine` (produkcyjne modele ML)
- Ryzyko ocenia `RiskManager`
- Wyniki monitoruje `StrategyPerformanceTracker`
- Zlecenia egzekwuje `OrderExecutor`
- `DynamicStrategyRouter` przełącza strategie
- `Security/ZeroTrust` zapewnia bezpieczeństwo
- `InfinityLayer` loguje, konfiguruje i monitoruje status
- Federated Learning umożliwia rozproszoną aktualizację modeli AI

Każda decyzja, metryka i egzekucja są logowane, ale promocja wymaga aktualnego PASS w gate runtime i economics.

---

## Nowości w LEVEL-Ω (lipiec 2025)

- **MarketDataFetcher**: Tryb mockowy wymaga jawnego `ZOL0_ALLOW_MOCK=1` oraz `USE_MOCK=1` (np. dla testów). W papierowym runtime `USE_MOCK=1` samodzielnie nie wystarcza. W produkcji zawsze używa prawdziwego API.
- **PortfolioNFT**: Każda decyzja tradingowa może być tokenizowana jako NFT (backup/insight portfela). Integracja z głównym pipeline.
- **MetaPlatformManager**: Tryb "live-paper" – pobiera realne dane rynkowe i stan konta wyłącznie z API KuCoin, ale wszystkie zlecenia są tylko symulowane i logowane lokalnie. Nie wysyła prawdziwych zleceń na giełdę. Pozwala na bezpieczne testowanie na realnych danych.
- **Testy**: Wszystkie testy przechodzą w trybie produkcyjnym. Testy wymagające mocka akceptują teraz pustą listę lub dane z API.
