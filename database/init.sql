CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    balance NUMERIC(12,2) DEFAULT 0,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payment_settings (
    id SERIAL PRIMARY KEY,
    system TEXT NOT NULL UNIQUE, -- 'sbp' или 'crypto'
    min_amount NUMERIC NOT NULL,
    currency TEXT NOT NULL, -- 'RUB' или 'USD'
    exchange_rate NUMERIC,  -- только для crypto
    updated_at TIMESTAMP DEFAULT NOW()
); 