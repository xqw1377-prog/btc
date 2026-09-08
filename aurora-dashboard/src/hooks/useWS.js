import { useEffect, useState, useCallback } from 'react';
import { wsClient } from '../services/wsClient';

export default function useWS() {
  const [system, setSystem] = useState({
    mode: 'UNKNOWN',
    engine: 'TREND',
    exposure: 0,
    leverage: 1,
    position: 'UNKNOWN',
    positionsState: 'UNKNOWN',
    killSwitch: false,
    engines: { trend: false, execution: false },
    balance: 0,
    equity: 0,
    unrealizedPnl: 0,
    positions: [],
    meta: { status: 'unknown', mode: null, updatedAt: null }
  });

  const [market, setMarket] = useState({
    price: 0,
    priceChange: 0,
    priceChangePercent: 0,
    regime: 'TRANSITION',
    confidence: 0,
    ema20: 0,
    ema60: 0,
    atr: 0,
    adx: 0,
    volatility: 0,
    volume: 0,
    spread: null,
    klines: [],
    meta: { status: 'unknown', mode: null, updatedAt: null }
  });

  const [risk, setRisk] = useState({
    currentDrawdown: null,
    maxDrawdown: null,
    dailyPnl: null,
    weeklyPnl: null,
    totalPnl: null,
    status: 'UNKNOWN',
    meta: { status: 'unknown', mode: null, updatedAt: null }
  });

  const [score, setScore] = useState(null);
  const [pnlData, setPnlData] = useState([]);
  const [trades, setTrades] = useState({
    items: [],
    meta: { status: 'unknown', source: 'EXCHANGE_READONLY', updatedAt: null }
  });
  const [connected, setConnected] = useState(false);

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
    if (Array.isArray(data)) {
      setPnlData(data);
    }
  }, []);

  const handleTradeUpdate = useCallback((data) => {
    setTrades(prev => ({ ...prev, items: [data, ...prev.items].slice(0, 20) }));
  }, []);

  const handleTradesUpdate = useCallback((data) => {
    if (Array.isArray(data)) {
      // 旧 list envelope 没有 freshness metadata，不能把收到数组等同于 fresh。
      setTrades(prev => ({ ...prev, items: data }));
    } else if (data && Array.isArray(data.items)) {
      setTrades({ items: data.items, meta: data.meta || { status: 'unknown' } });
    }
  }, []);

  useEffect(() => {
    wsClient.connect();

    // 回调必须用具名变量持有引用，cleanup 里 off() 才能按引用精确移除，
    // 否则每次重渲染都会叠加监听器，导致同一条消息触发多次 setState。
    const handleOpen = () => {
      console.log('WebSocket connected');
      setConnected(true);
    };
    const handleClose = () => {
      console.log('WebSocket disconnected');
      setConnected(false);
    };

    wsClient.on('open', handleOpen);
    wsClient.on('close', handleClose);
    wsClient.on('system', handleSystemUpdate);
    wsClient.on('market', handleMarketUpdate);
    wsClient.on('risk', handleRiskUpdate);
    wsClient.on('score', handleScoreUpdate);
    wsClient.on('pnl', handlePnlUpdate);
    wsClient.on('trade', handleTradeUpdate);
    wsClient.on('trades', handleTradesUpdate);

    return () => {
      wsClient.off('open', handleOpen);
      wsClient.off('close', handleClose);
      wsClient.off('system', handleSystemUpdate);
      wsClient.off('market', handleMarketUpdate);
      wsClient.off('risk', handleRiskUpdate);
      wsClient.off('score', handleScoreUpdate);
      wsClient.off('pnl', handlePnlUpdate);
      wsClient.off('trade', handleTradeUpdate);
      wsClient.off('trades', handleTradesUpdate);
    };
  }, [handleSystemUpdate, handleMarketUpdate, handleRiskUpdate, handleScoreUpdate, handlePnlUpdate, handleTradeUpdate, handleTradesUpdate]);

  return {
    system,
    market,
    risk,
    score,
    pnlData,
    trades,
    connected
  };
}