CREATE TABLE IF NOT EXISTS fear_greed_index (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    index_date DATE NOT NULL,
    value TINYINT UNSIGNED NOT NULL,
    value_classification VARCHAR(32) NOT NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'alternative.me',
    source_timestamp BIGINT UNSIGNED NULL,
    time_until_update_seconds INT UNSIGNED NULL,
    raw_response JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_fear_greed_index_date_source (index_date, source),
    KEY idx_fear_greed_index_date (index_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
