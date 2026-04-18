# LEVEL-Ω-REALITY-CHECK

**Cel:** Ostatnia faza stabilizacji przed pełnym uruchomieniem produkcyjnym. Eliminacja mocków, wypełnienie stubów, domknięcie integracji i zapewnienie pełnego monitoringu.

---

## 🔧 Zadania

### 1. MarketDataFetcher – produkcyjny tryb danych
- [ ] Usuń tryb mockowy z `MarketDataFetcher`
- [ ] Wprowadź flagę ENV `USE_MOCK=False`
- [ ] W testach nadal pozwól na użycie mocka (ENV: `USE_MOCK=True`)
- [ ] Dodaj ostrzeżenie, jeśli mock działa w trybie produkcyjnym

### 2. utils/health_check.py – realna obsługa checków
- [ ] `check_api()` – sprawdzanie, czy API odpowiada i zwraca dane
- [ ] `check_ticks()` – czy napływają nowe ticki z giełdy
- [ ] `check_bot_status()` – czy bot podejmuje decyzje, jest w stanie aktywnym
- [ ] `health_check()` – wrapper do uruchamiania wszystkich powyższych

### 3. PortfolioNFT – integracja
- [ ] Połącz `PortfolioNFT` z `QuantumPortfolioOptimizer` lub `PositionManager`
- [ ] Zapisuj snapshoty strategii jako NFT (lub logi)
- [ ] Jeśli niepotrzebna – usuń i zdeprecjonuj plik

### 4. MetaPlatformManager – pełna integracja
- [ ] Zapewnij, że `MetaPlatformManager` synchronizuje aktualizacje z platform (API/WebSocket)
- [ ] Zbiera i loguje stany platform
- [ ] Jeśli jest eksperymentalny – oznacz jako taki lub przenieś do `experimental/`

---

## 📅 Przewidywany czas realizacji

1–2 dni robocze z testami regresji i sanity-checkami.

---

## 🔚 Poziom kończy:
- Całkowite usunięcie stubów
- Uspójnienie produkcyjnych komponentów
- Gotowość systemu do integracji frontendu i deploymentu
✅ TODO.md (z checkboxami do CI/CD)
