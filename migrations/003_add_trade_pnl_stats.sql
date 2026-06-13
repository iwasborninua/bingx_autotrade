ALTER TABLE trades
    ADD COLUMN last_price DECIMAL(30,12) NULL AFTER fee_rate,
    ADD COLUMN last_pnl DECIMAL(30,12) NULL AFTER last_roi,
    ADD COLUMN close_price DECIMAL(30,12) NULL AFTER last_pnl,
    ADD COLUMN realized_roi DECIMAL(20,8) NULL AFTER close_price,
    ADD COLUMN realized_pnl DECIMAL(30,12) NULL AFTER realized_roi;
