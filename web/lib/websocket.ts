import { io, Socket } from 'socket.io-client';
import { SystemState, MarketState, RiskState, Trade, EquityPoint } from '../types';

const SOCKET_URL = process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:8000';

let socket: Socket | null = null;

export const connectSocket = () => {
  if (socket) return socket;
  
  socket = io(SOCKET_URL, {
    transports: ['websocket'],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
  });
  
  return socket;
};

export const subscribeToSystemState = (callback: (state: SystemState) => void) => {
  const socket = connectSocket();
  socket.on('system:state', callback);
  return () => socket.off('system:state', callback);
};

export const subscribeToMarketState = (callback: (state: MarketState) => void) => {
  const socket = connectSocket();
  socket.on('market:state', callback);
  return () => socket.off('market:state', callback);
};

export const subscribeToRiskState = (callback: (state: RiskState) => void) => {
  const socket = connectSocket();
  socket.on('risk:state', callback);
  return () => socket.off('risk:state', callback);
};

export const subscribeToTrades = (callback: (trade: Trade) => void) => {
  const socket = connectSocket();
  socket.on('trade:new', callback);
  return () => socket.off('trade:new', callback);
};

export const subscribeToEquityCurve = (callback: (points: EquityPoint[]) => void) => {
  const socket = connectSocket();
  socket.on('equity:update', callback);
  return () => socket.off('equity:update', callback);
};

export const setKillSwitch = (state: boolean) => {
  const socket = connectSocket();
  socket.emit('system:kill-switch', { state });
};

export const setSystemMode = (mode: SystemState['mode']) => {
  const socket = connectSocket();
  socket.emit('system:mode', { mode });
};

export const disconnectSocket = () => {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
};
