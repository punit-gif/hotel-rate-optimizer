CREATE TABLE IF NOT EXISTS reservations(
  id SERIAL PRIMARY KEY,
  stay_date DATE NOT NULL,
  room_type TEXT NOT NULL,
  occupancy INT NOT NULL,
  adr NUMERIC NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_res_stay_room ON reservations(stay_date, room_type);

CREATE TABLE IF NOT EXISTS competitor_rates(
  id SERIAL PRIMARY KEY,
  stay_date DATE NOT NULL,
  competitor TEXT NOT NULL,
  room_type TEXT NOT NULL,
  rate NUMERIC NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_comp_stay_room ON competitor_rates(stay_date, room_type);
CREATE INDEX IF NOT EXISTS idx_comp_stay_comp ON competitor_rates(stay_date, competitor);

CREATE TABLE IF NOT EXISTS forecasts(
  id SERIAL PRIMARY KEY,
  run_date DATE NOT NULL,
  stay_date DATE NOT NULL,
  room_type TEXT NOT NULL,
  demand_forecast NUMERIC NOT NULL,
  rec_adr NUMERIC NOT NULL,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fc_stay_room ON forecasts(stay_date, room_type);

CREATE TABLE IF NOT EXISTS users(
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
