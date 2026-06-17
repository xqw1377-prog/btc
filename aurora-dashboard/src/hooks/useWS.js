import { useEffect, useState, useCallback } from 'react';
import { wsClient } from '../services/wsClient';

export default function useWS() {
  const [system, setSystem] = useState({
    mode: 'NORMAL',
    engine: 'TREND',
    exposure: 0,
    leverage: 1,
    position: 'FLAT',
    killSwitch: false,
    engines: { trend: true, execution: true }
  });

  const [market, setMarket] = useState({
    price: 0,
    priceChange: 0,
    priceChangePercent: 0,
    regime: 'TREND',
    confidence: 0,
    ema20: 0,
    ema60: 0,
    atr: 0,
    volatility: 0,
    volume: 0,
    spread: 0
  });

  const [risk, setRisk] = useState({
    currentDrawdown: 0,
    maxDrawdown: 0,
    dailyPnl: 0,
    weeklyPnl: 0,
    totalPnl: 0,
    status: 'SAFE'
  });

  const [score, setScore] = useState(50);

  const [pnlData, setPnlData] = useState([]);

  const [trades, setTrades] = useState([]);

  const handleSystemUpdate = useCallback((data) => {
    setSystem(prev => ({ ...prev, ...data }));
  }, []);

  const handleMarketUpdate = useCallback((data) => {
    setMarket(prev => ({ ...prev, ...data }));
  }, []);

  const handleRiskUpdate = useCallback((data) => {
    setRisk(prev => ({ ...prev, ...data }));
  }, []);

  const handleScoreUpdate = useCallback((data) => {
    setScore(data);
  }, []);

  const handlePnlUpdate = useCallback((data) => {
    setPnlData(data);
  }, []);

  const handleTradeUpdate = useCallback((data) => {
    setTrades(prev => [data, ...prev].slice(0, 20));
  }, []);

  useEffect(() => {
    wsClient.connect();

    wsClient.on('system', handleSystemUpdate);
    wsClient.on('market', handleMarketUpdate);
    wsClient.on('risk', handleRiskUpdate);
    wsClient.on('score', handleScoreUpdate);
    wsClient.on('pnl', handlePnlUpdate);
    wsClient.on('trade', handleTradeUpdate);

    return () => {
      wsClient.off('system', handleSystemUpdate);
      wsClient.off('market', handleMarketUpdate);
      wsClient.off('risk', handleRiskUpdate);
      wsClient.off('score', handleScoreUpdate);
      wsClient.off('pnl', handlePnlUpdate);
      wsClient.off('trade', handleTradeUpdate);
    };
  }, [handleSystemUpdate, handleMarketUpdate, handleRiskUpdate, handleScoreUpdate, handlePnlUpdate, handleTradeUpdate]);

  return {
    system,
    market,
    risk,
    score,
    pnlData,
    trades
  };
}
