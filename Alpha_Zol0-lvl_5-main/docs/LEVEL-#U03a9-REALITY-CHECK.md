# LEVEL-Ω-REALITY-CHECK

**Cel:** Rejestr aktualnego stanu stabilizacji runtime. Statusy ponizej sa
oparte na kodzie i testach w repo, nie na zalozeniach o gotowosci
produkcyjnej.

---

## Zadania

### 1. MarketDataFetcher - PAPER-first data gating
- [x] `USE_MOCK` obsluguje wartosci bool-like (`1`, `true`, `yes`, `on`).
- [x] Mock OHLCV w PAPER wymaga dodatkowego opt-in `ZOL0_ALLOW_MOCK=1`.
- [x] `USE_MOCK` w LIVE jest blokowany fail-closed.
- [x] Testy moga wlaczac mock jawnie.
- [x] Poza pytest runtime logowane jest ostrzezenie o syntetycznym OHLCV.
- [ ] Pelne usuniecie trybu mockowego nie jest wykonane; mock pozostaje
      kontrolowanym narzedziem testowym/offline.

### 2. utils/health_check.py - runtime health aggregation
- [x] `check_api()` sprawdza publiczny endpoint KuCoin i nie akceptuje pustego
      payloadu.
- [x] `check_ticks()` sprawdza swiezosc lokalnego decision logu albo ostatniej
      decyzji w DB.
- [x] `check_bot_status()` sprawdza PID albo aktywnosc decyzyjna w DB.
- [x] `health_check()` agreguje `api`, `ticks`, `bot` i zapisuje JSONL do
      `logs/health.log`.
- [ ] Nie ma dowodu live runtime na ciagly naplyw tickow z gieldy w tej
      dokumentacji; status wymaga artefaktow runtime.

### 3. PortfolioNFT – integracja
- [x] `PortfolioNFT` jest podlaczony do `PositionManager`.
- [x] Otwarcie i zamkniecie pozycji emituje snapshot strategii.
- [x] Snapshot moze byc zapisany do JSONL, jesli ustawiono `log_path`.
- [ ] Integracja z `QuantumPortfolioOptimizer` nie zostala potwierdzona w tym
      patchu.

### 4. MetaPlatformManager – pełna integracja
- [x] `MetaPlatformManager` blokuje platformy inne niz KuCoin.
- [x] Synchronizuje stan przez API, lokalny portfel i eventy websocket adaptera.
- [x] Zbiera i loguje `platform_states`.
- [x] Domyslny adapter `KucoinWebSocketAdapter` jest dolaczany dla KuCoin.
- [ ] WebSocket transport jest testowany offline fake session/fake app; gotowosc
      runtime wymaga swiezych artefaktow z uruchomienia PAPER.

---

## Przewidywany czas realizacji

Brak deklaracji terminu. Status powinien wynikac z testow i artefaktow runtime.

---

## Aktualny wynik
- Mock nie jest usuniety; jest ograniczony gate'ami i testami.
- Health check ma agregacje API/tick/bot, ale readiness runtime wymaga logow i
  artefaktow PAPER.
- MetaPlatformManager ma KuCoin-only state sync i adapter websocket, ale nie jest
  dowodem gotowosci LIVE.
- CI obejmuje osobny job regresyjny dla sprawdzonego wycinka LEVEL-OMEGA.
