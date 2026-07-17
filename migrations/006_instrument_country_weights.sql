-- Handmatig ingevoerde landenwegingen voor ETF's/fondsen.
-- weight_pct is een percentage van de fondswaarde, bijvoorbeeld 62.5.

CREATE TABLE IF NOT EXISTS instrument_country_weights (
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    country       TEXT NOT NULL,
    weight_pct    TEXT NOT NULL,
    PRIMARY KEY (instrument_id, country)
);
