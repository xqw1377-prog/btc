import React from 'react';
import { Card, CardContent, Typography, Box, Chip, Avatar, Stack } from '@mui/material';
import {
  Activity,
  Pause,
  Stop,
  PlayArrow,
  TrendingUp,
  TrendingDown,
  Minus,
  Zap,
  Shield,
  Gauge,
} from '@mui/icons-material';
import { SystemState } from '../types';

interface SystemStateCardProps {
  state: SystemState;
  onKillSwitch: (state: boolean) => void;
  onModeChange: (mode: SystemState['mode']) => void;
}

const modeConfig = {
  NORMAL: { label: 'NORMAL', color: 'success', icon: PlayArrow, bgColor: 'rgba(76, 175, 80, 0.15)' },
  CAUTIOUS: { label: 'CAUTIOUS', color: 'warning', icon: Gauge, bgColor: 'rgba(255, 193, 7, 0.15)' },
  RISK_OFF: { label: 'RISK OFF', color: 'error', icon: Pause, bgColor: 'rgba(244, 67, 54, 0.15)' },
  EMERGENCY: { label: 'EMERGENCY', color: 'error', icon: Stop, bgColor: 'rgba(233, 30, 99, 0.15)' },
};

const sideConfig = {
  LONG: { label: 'LONG', color: 'success', icon: TrendingUp },
  SHORT: { label: 'SHORT', color: 'error', icon: TrendingDown },
  FLAT: { label: 'FLAT', color: 'info', icon: Minus },
};

export const SystemStateCard: React.FC<SystemStateCardProps> = ({ state, onKillSwitch, onModeChange }) => {
  const mode = modeConfig[state.mode];
  const side = sideConfig[state.position.side];
  const ModeIcon = mode.icon;
  const SideIcon = side.icon;

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom sx={{ fontWeight: 'bold', color: '#1a1a2e' }}>
          SYSTEM STATE
        </Typography>
        
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 4 }}>
          <Avatar 
            sx={{ 
              width: 80, 
              height: 80, 
              bgcolor: mode.bgColor,
              marginRight: 3,
              animation: state.mode === 'NORMAL' ? 'pulse 2s infinite' : 'none'
            }}
          >
            <ModeIcon sx={{ width: 40, height: 40, color: mode.color === 'success' ? '#4caf50' : mode.color === 'warning' ? '#ffc107' : '#f44336' }} />
          </Avatar>
          
          <Box>
            <Chip 
              label={mode.label} 
              color={mode.color as any} 
              size="large"
              onClick={() => {
                const modes: SystemState['mode'][] = ['NORMAL', 'CAUTIOUS', 'RISK_OFF', 'EMERGENCY'];
                const currentIndex = modes.indexOf(state.mode);
                const nextMode = modes[(currentIndex + 1) % modes.length];
                onModeChange(nextMode);
              }}
              sx={{ cursor: 'pointer', mb: 2 }}
            />
            
            <Typography variant="body2" color="text.secondary">
              Click to cycle mode
            </Typography>
          </Box>
        </Box>

        <Grid container spacing={3}>
          <Grid item xs={4}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <SideIcon sx={{ marginRight: 1, color: side.color === 'success' ? '#4caf50' : side.color === 'error' ? '#f44336' : '#2196f3' }} />
              <Typography variant="subtitle2">POSITION</Typography>
            </Box>
            <Typography variant="h4" fontWeight="bold">
              {side.label}
            </Typography>
          </Grid>

          <Grid item xs={4}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Zap sx={{ marginRight: 1, color: '#ff9800' }} />
              <Typography variant="subtitle2">LEVERAGE</Typography>
            </Box>
            <Typography variant="h4" fontWeight="bold">
              {state.position.leverage}x
            </Typography>
          </Grid>

          <Grid item xs={4}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Activity sx={{ marginRight: 1, color: '#9c27b0' }} />
              <Typography variant="subtitle2">EXPOSURE</Typography>
            </Box>
            <Typography variant="h4" fontWeight="bold">
              {state.position.exposure}%
            </Typography>
          </Grid>
        </Grid>

        <Box sx={{ mt: 3, pt: 3, borderTop: '1px solid #eee' }}>
          <Typography variant="subtitle2" mb={2}>ENGINES STATUS</Typography>
          <Stack direction="row" spacing={2}>
            <Chip 
              label={`Trend Engine ${state.engines.trend ? 'ON' : 'OFF'}`}
              color={state.engines.trend ? 'success' : 'error'}
              size="small"
            />
            <Chip 
              label={`Execution Engine ${state.engines.execution ? 'ON' : 'OFF'}`}
              color={state.engines.execution ? 'success' : 'error'}
              size="small"
            />
          </Stack>
        </Box>

        <Box sx={{ mt: 3 }}>
          <button
            onClick={() => onKillSwitch(!state.killSwitch)}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: state.killSwitch ? '#f44336' : '#4caf50',
              color: 'white',
              fontWeight: 'bold',
              fontSize: '16px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
            }}
          >
            <Shield />
            {state.killSwitch ? 'KILL SWITCH ACTIVE - CLICK TO DISABLE' : 'ACTIVATE KILL SWITCH'}
          </button>
        </Box>
      </CardContent>
    </Card>
  );
};

import { Grid } from '@mui/material';
