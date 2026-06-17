from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import os
import json

app = FastAPI(title="AURORA API Gateway", version="1.0")

redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = int(os.getenv('REDIS_PORT', 6379))
r = redis.Redis(host=redis_host, port=redis_port)

class KillSwitchRequest(BaseModel):
    state: str

class SystemStateResponse(BaseModel):
    kill_switch: str
    system_mode: str
    risk_multiplier: float

@app.get("/health")
async def health_check():
    try:
        r.ping()
        return {"status": "healthy", "service": "aurora-api-gateway"}
    except Exception as e:
        raise HTTPException(status_code=503, detail="Service unavailable")

@app.get("/system/state", response_model=SystemStateResponse)
async def get_system_state():
    try:
        kill_switch = r.get('system:kill_switch')
        system_mode = r.get('system:mode')
        risk_multiplier = r.get('system:risk_multiplier')
        
        return {
            "kill_switch": kill_switch.decode() if kill_switch else "OFF",
            "system_mode": system_mode.decode() if system_mode else "NORMAL",
            "risk_multiplier": float(risk_multiplier.decode()) if risk_multiplier else 1.0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/system/kill-switch")
async def set_kill_switch(request: KillSwitchRequest):
    if request.state not in ["ON", "OFF"]:
        raise HTTPException(status_code=400, detail="Invalid state. Must be 'ON' or 'OFF'")
    
    try:
        r.set('system:kill_switch', request.state)
        
        if request.state == "ON":
            r.set('system:mode', "RISK_OFF")
            r.set('system:risk_multiplier', 0.0)
        else:
            r.set('system:mode', "NORMAL")
            r.set('system:risk_multiplier', 1.0)
        
        return {"message": f"Kill switch set to {request.state}", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/system/mode")
async def set_system_mode(mode: str):
    valid_modes = ["NORMAL", "CAUTIOUS", "RISK_OFF", "EMERGENCY"]
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of {valid_modes}")
    
    try:
        r.set('system:mode', mode)
        
        multipliers = {
            "NORMAL": 1.0,
            "CAUTIOUS": 0.6,
            "RISK_OFF": 0.3,
            "EMERGENCY": 0.0
        }
        r.set('system:risk_multiplier', multipliers[mode])
        
        return {"message": f"System mode set to {mode}", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/trades/recent")
async def get_recent_trades(limit: int = 10):
    try:
        trades = r.lrange('trades:recent', 0, limit - 1)
        return [json.loads(t.decode()) for t in trades]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_metrics():
    try:
        metrics = {
            'total_trades': int(r.get('metrics:total_trades') or 0),
            'win_trades': int(r.get('metrics:win_trades') or 0),
            'total_pnl': float(r.get('metrics:total_pnl') or 0),
            'max_drawdown': float(r.get('metrics:max_drawdown') or 0),
            'current_equity': float(r.get('metrics:current_equity') or 0)
        }
        metrics['win_rate'] = metrics['win_trades'] / max(metrics['total_trades'], 1) * 100
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/system/rebalance")
async def trigger_rebalance():
    try:
        r.publish('system:commands', json.dumps({'command': 'rebalance'}))
        return {"message": "Rebalance triggered", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/system/stop")
async def stop_trading():
    try:
        r.set('system:kill_switch', 'ON')
        r.set('system:mode', 'EMERGENCY')
        r.set('system:risk_multiplier', 0.0)
        r.publish('system:commands', json.dumps({'command': 'stop'}))
        return {"message": "Trading stopped", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
