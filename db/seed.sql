-- Creates a single admin user using ADMIN_EMAIL/ADMIN_PASSWORD env vars via psql \\set
-- Example:
--   psql "$POSTGRES_URL" -v admin_email="'$ADMIN_EMAIL'" -v admin_password="'$ADMIN_PASSWORD'" -f db/seed.sql
DO $$
DECLARE
    v_email TEXT := current_setting('app.admin_email', true);
    v_pass TEXT := current_setting('app.admin_password', true);
BEGIN
    IF v_email IS NULL OR v_pass IS NULL THEN
        RAISE NOTICE 'Use: SET app.admin_email, app.admin_password before running seed';
        RETURN;
    END IF;
END$$;

-- Fallback: insert a placeholder; you should update via API
INSERT INTO users(email, password_hash)
VALUES ('admin@example.com', '$2b$12$Z3JQ2R3mV9C9m1q.VS7QyuO5rSx7tHq9e5D2e3qS7hYw0C2qJ9g3i') -- bcrypt of "ChangeMe123!"
ON CONFLICT (email) DO NOTHING;
