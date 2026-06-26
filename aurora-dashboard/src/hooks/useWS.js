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
    engines: { trend: true, execution: true },
    balance: 0,
    equity: 0,
    unrealizedPnl: 0,
    positions: []
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
    spread: 0,
    klines: []
  });

  const [risk, setRisk] = useState({
    currentDrawdown: 0,
    maxDrawdown: 0,
    dailyPnl: 0,
    weeklyPnl: 0,
    totalPnl: 0,
    status: 'SAFE'
  });

  const [score, setScore] = useState(0);
  const [pnlData, setPnlData] = useState([]);
  const [trades, setTrades] = useState([]);
  const [connected, setConnected] = useState(false);

  const handleSystemUpdate = useCallback((data) => {
    console.log('System update:', data);
    setSystem(prev => ({ ...prev, ...data }));
  }, []);

  const handleMarketUpdate = useCallback((data) => {
    console.log('Market update:', data.price);
    setMarket(prev => ({ ...prev, ...data }));
  }, []);

  const handleRiskUpdate = useCallback((data) => {
    console.log('Risk update:', data);
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
    setTrades(prev => [data, ...prev].slice(0, 20));
  }, []);

  const handleTradesUpdate = useCallback((data) => {
    console.log('Trades update received:', Array.isArray(data) ? data.length : typeof data);
    if (Array.isArray(data)) {
      setTrades(data);
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