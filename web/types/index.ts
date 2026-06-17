export type SystemMode = 'NORMAL' | 'CAUTIOUS' | 'RISK_OFF' | 'EMERGENCY';

export type MarketRegime = 'TREND' | 'RANGE' | 'TRANSITION' | 'LIQUIDITY_DRIVEN';

export type PositionSide = 'LONG' | 'SHORT' | 'FLAT';

export type RiskStatus = 'SAFE' | 'WARNING' | 'CRITICAL';

export interface SystemState {
  mode: SystemMode;
  position: {
    side: PositionSide;
    leverage: number;
    exposure: number;
  };
  engines: {
    trend: boolean;
    execution: boolean;
  };
  killSwitch: boolean;
  tradeScore: number;
}

export interface MarketState {
  price: number;
  priceChange: number;
  priceChangePercent: number;
  regime: MarketRegime;
  confidence: number;
  ema20: number;
  ema60: number;
  atr: number;
  volatility: number;
  volume: number;
  spread: number;
}

export interface RiskState {
  currentDrawdown: number;
  maxDrawdown: number;
  dailyPnl: number;
  weeklyPnl: number;
  totalPnl: number;
  status: RiskStatus;
}

export interface Trade {
  id: string;
  timestamp: string;
  engine: 'TREND' | 'EXECUTION';
  side: 'BUY' | 'SELL';
  entryPrice: number;
  exitPrice: number | null;
  quantity: number;
  pnl: number;
  pnlPercent: number;
  reason: string;
  regime: MarketRegime;
  confidence: number;
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
}
