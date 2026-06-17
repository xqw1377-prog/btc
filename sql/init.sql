CREATE TABLE IF NOT EXISTS market_data (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    open NUMERIC(18, 8) NOT NULL,
    high NUMERIC(18, 8) NOT NULL,
    low NUMERIC(18, 8) NOT NULL,
    close NUMERIC(18, 8) NOT NULL,
    volume NUMERIC(20, 8) NOT NULL,
    vwap NUMERIC(18, 8),
    oi NUMERIC(20, 8),
    funding_rate NUMERIC(12, 8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_data_timestamp ON market_data(timestamp);

CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    client_order_id VARCHAR(64) UNIQUE,
    symbol VARCHAR(16) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(16) NOT NULL,
    quantity NUMERIC(18, 8) NOT NULL,
    price NUMERIC(18, 8),
    filled_quantity NUMERIC(18, 8) DEFAULT 0,
    filled_price NUMERIC(18, 8),
    status VARCHAR(16) NOT NULL,
    pnl NUMERIC(18, 8) DEFAULT 0,
    engine_type VARCHAR(16),
    regime VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at);

CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    signal_type VARCHAR(16) NOT NULL,
    direction VARCHAR(8),
    engine_type VARCHAR(16),
    confidence NUMERIC(5, 2),
    regime VARCHAR(32),
    features JSONB,
    risk_approved BOOLEAN DEFAULT FALSE,
    executed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at);

CREATE TABLE IF NOT EXISTS system_state (
    id SERIAL PRIMARY KEY,
    state_name VARCHAR(32) UNIQUE NOT NULL,
    state_value VARCHAR(128) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO system_state (state_name, state_value) VALUES ('kill_switch', 'OFF') ON CONFLICT DO NOTHING;
INSERT INTO system_state (state_name, state_value) VALUES ('system_mode', 'NORMAL') ON CONFLICT DO NOTHING;
INSERT INTO system_state (state_name, state_value) VALUES ('risk_multiplier', '1.0') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS equity_curve (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    equity NUMERIC(18, 2) NOT NULL,
    balance NUMERIC(18, 2) NOT NULL,
    drawdown NUMERIC(8, 4),
    pnl NUMERIC(18, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_equity_curve_timestamp ON equity_curve(timestamp);
