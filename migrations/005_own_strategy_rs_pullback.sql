CREATE TABLE IF NOT EXISTS own_strategy_signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    strategy_name VARCHAR(128) NOT NULL,
    signal_source VARCHAR(32) NOT NULL DEFAULT 'own',
    symbol VARCHAR(64) NOT NULL,
    bingx_symbol VARCHAR(64) NULL,
    direction VARCHAR(16) NOT NULL,
    setup_type VARCHAR(128) NOT NULL,
    timeframe VARCHAR(16) NOT NULL,
    signal_ts DATETIME NOT NULL,
    signal_close DECIMAL(30, 12) NOT NULL,
    entry_model VARCHAR(64) NOT NULL,
    entry_price DECIMAL(30, 12) NOT NULL,
    stop_model VARCHAR(64) NOT NULL,
    stop_price DECIMAL(30, 12) NOT NULL,
    risk_price DECIMAL(30, 12) NOT NULL,
    risk_pct DECIMAL(18, 8) NOT NULL,
    tp1_price DECIMAL(30, 12) NOT NULL,
    tp2_price DECIMAL(30, 12) NOT NULL,
    tp3_price DECIMAL(30, 12) NOT NULL,
    atr_period INT NOT NULL,
    atr_value DECIMAL(30, 12) NOT NULL,
    relative_strength_1h DECIMAL(18, 8) NULL,
    price_change_1h DECIMAL(18, 8) NULL,
    volume_ratio_15m DECIMAL(18, 8) NULL,
    oi_change_15m DECIMAL(18, 8) NULL,
    btc_change_1h DECIMAL(18, 8) NULL,
    score DECIMAL(18, 8) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    skip_reason VARCHAR(255) NULL,
    features_json JSON NULL,
    reason_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_own_signal (strategy_name, symbol, timeframe, signal_ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS market_candles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(64) NOT NULL,
    exchange VARCHAR(32) NOT NULL,
    timeframe VARCHAR(16) NOT NULL,
    ts DATETIME NOT NULL,
    open DECIMAL(30, 12) NOT NULL,
    high DECIMAL(30, 12) NOT NULL,
    low DECIMAL(30, 12) NOT NULL,
    close DECIMAL(30, 12) NOT NULL,
    volume DECIMAL(30, 12) NULL,
    source VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_candle (symbol, exchange, timeframe, ts),
    INDEX idx_symbol_timeframe_ts (symbol, timeframe, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS market_open_interest (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(64) NOT NULL,
    exchange VARCHAR(32) NOT NULL,
    timeframe VARCHAR(16) NOT NULL,
    ts DATETIME NOT NULL,
    open_interest DECIMAL(30, 12) NOT NULL,
    source VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_oi (symbol, exchange, timeframe, ts),
    INDEX idx_symbol_timeframe_ts (symbol, timeframe, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS symbol_mappings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    normalized_symbol VARCHAR(64) NOT NULL,
    bingx_symbol VARCHAR(64) NULL,
    coinalyze_symbol VARCHAR(128) NULL,
    base_asset VARCHAR(32) NULL,
    quote_asset VARCHAR(32) NULL,
    market_type VARCHAR(32) NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_crypto BOOLEAN DEFAULT TRUE,
    raw_bingx_json JSON NULL,
    raw_coinalyze_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_normalized_symbol (normalized_symbol),
    INDEX idx_bingx_symbol (bingx_symbol),
    INDEX idx_coinalyze_symbol (coinalyze_symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE trades ADD COLUMN signal_source VARCHAR(32) NOT NULL DEFAULT 'telegram';
ALTER TABLE trades ADD COLUMN strategy_name VARCHAR(128) NULL;
ALTER TABLE trades ADD COLUMN setup_type VARCHAR(128) NULL;
ALTER TABLE trades ADD COLUMN source_signal_id BIGINT NULL;
ALTER TABLE trades ADD COLUMN entry_model VARCHAR(64) NULL;
ALTER TABLE trades ADD COLUMN stop_model VARCHAR(64) NULL;
ALTER TABLE trades ADD COLUMN r_model VARCHAR(64) NULL;
ALTER TABLE trades ADD COLUMN initial_stop_price DECIMAL(30, 12) NULL;
ALTER TABLE trades ADD COLUMN current_stop_price DECIMAL(30, 12) NULL;
ALTER TABLE trades ADD COLUMN risk_price DECIMAL(30, 12) NULL;
ALTER TABLE trades ADD COLUMN risk_pct DECIMAL(18, 8) NULL;
ALTER TABLE trades ADD COLUMN tp3_reached_at DATETIME NULL;
ALTER TABLE trades ADD COLUMN max_favorable_r DECIMAL(18, 8) NULL;
ALTER TABLE trades ADD COLUMN max_adverse_r DECIMAL(18, 8) NULL;
ALTER TABLE trades ADD COLUMN exchange_sl_order_id VARCHAR(128) NULL;
ALTER TABLE trades ADD COLUMN exchange_tp_order_id VARCHAR(128) NULL;
ALTER TABLE trades ADD COLUMN sl_move_status VARCHAR(64) NULL;
ALTER TABLE trades ADD COLUMN sl_move_error TEXT NULL;
ALTER TABLE trades ADD COLUMN sl_moved_after_tp1_at DATETIME NULL;
ALTER TABLE trades ADD COLUMN protection_status VARCHAR(64) NULL;
