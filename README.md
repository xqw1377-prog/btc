# AURORA Capital Operating System

> **AURORA is a single-asset Capital Operating System built around BTC that achieves sustained capital growth through strategy perception → capital decision → risk adjudication → stateless execution.**

---

## System Essence

AURORA is not a trading system. It is a **Capital Operating System** that:

1. **Perceives** market state through multiple signal providers
2. **Decides** capital allocation through a single brain
3. **Adjudicates** risk through a constitutional kernel
4. **Executes** orders through a stateless engine

*"AURORA doesn't trade BTC. It runs a capital decision system around BTC."*

---

## Four Core Kernels

### 1. Strategy Layer (Perception)
- **Role**: Generate market interpretations only
- **Components**: TrendSignalProvider, BreakoutSignalProvider, MomentumSignalProvider, MeanReversionSignalProvider
- **Output**: `Signal[]` (no decisions)
- **File**: `aurora/signal_providers.py`

### 2. Portfolio Brain (Decision)
- **Role**: Sole capital decision maker
- **Responsibilities**: Direction, position size, strategy mix
- **Output**: `BrainDecision`
- **File**: `aurora/portfolio_brain_v3.py`

### 3. Risk Kernel (Adjudication)
- **Role**: Capital constitution - can override any decision
- **Zones**: SAFE (<0.4), WARNING (0.4-0.7), CRITICAL (>0.7)
- **Actions**: ALLOW, REDUCE, FREEZE
- **Output**: `RiskVerdict`
- **File**: `aurora/risk_kernel_v2.py`

### 4. Execution Engine (Action)
- **Role**: Stateless executor - no judgment, no thinking, no prediction
- **Capabilities**: Idempotent orders, retry logic, position reconciliation
- **Output**: `ExecutionResult`
- **File**: `aurora/execution_engine_v2.py`

---

## Complete Data Flow

```
BTC Market
    ↓
Feature Engine (15+ indicators)
    ↓
Market State Engine (TREND/RANGE/TRANSITION)
    ↓
Strategy Signals (4 providers)
    ↓
PORTFOLIO BRAIN (regime-weighted decision)
    ↓
RISK KERNEL (score → zone → action → multiplier)
    ↓
CAPITAL OS (position sizing cap)
    ↓
EXECUTION ENGINE (stateless order placement)
    ↓
BTC Market
```

---

## Three Governing Principles

### 1. Single Source of Truth
> Only Portfolio Brain decides "what to do"

### 2. Risk Supremacy
> Risk Kernel can override any decision - it is the constitutional court

### 3. Execution Apathy
> Execution Engine has zero strategy logic

---

## System Capability Matrix

| Dimension | Rating | Evidence |
|-----------|--------|----------|
| Strategy Capability | 8/10 | 4 signal providers, regime-adaptive weighting |
| System Architecture | 9/10 | Strict sequential gating, no shortcut paths |
| Risk Architecture | 8.5/10 | Three-layer defense: RiskKernel + COS + Kernel |
| Institutional Grade | 8-9/10 | Idempotent execution, state reconciliation |
| Scalability | 9/10 | Modular design, clear layer boundaries |

---

## Quick Start

### 1. Environment Setup

```bash
cp .env.example .env
# Edit .env with your Binance API credentials
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run System

```bash
python aurora_kernel_v4.py
```

---

## Key Files

| Component | File Path |
|-----------|-----------|
| Kernel V4 (Main) | `aurora_kernel_v4.py` |
| Portfolio Brain | `aurora/portfolio_brain_v3.py` |
| Risk Kernel | `aurora/risk_kernel_v2.py` |
| Execution Engine | `aurora/execution_engine_v2.py` |
| Capital OS | `aurora/capital_operating_system.py` |
| Signal Providers | `aurora/signal_providers.py` |
| Feature Engine | `aurora/feature_engine.py` |
| Market State Engine | `aurora/market_state_engine_v2.py` |
| Kernel Types | `aurora/kernel_types.py` |

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed system architecture diagram.

See [AURORA_SYSTEM_DEFINITION.md](AURORA_SYSTEM_DEFINITION.md) for complete institutional definition.

---

## License

Private - All Rights Reserved
