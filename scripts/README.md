# Database Scripts

## verify_businesses_rls.sql

Verifies that row-level security (RLS) policies exist on the `businesses` table after applying the `*_businesses_rls_policies` migration.

### When to Run

Run after applying the businesses RLS migration to your Supabase (or Postgres) database, to confirm that the three policies (SELECT, INSERT, UPDATE for `authenticated`) are present.

### How to Run

**Using Supabase SQL Editor:** Paste the contents of `scripts/verify_businesses_rls.sql` and run.

**Using psql:**
```bash
psql "your_database_url" -f scripts/verify_businesses_rls.sql
```

### What It Does

1. Shows whether RLS is enabled on `public.businesses`.
2. Lists all policies on `businesses` (names, command, roles, expressions).

### Notes

- Requires PostgreSQL (e.g. Supabase). Not for SQLite.
- Full verification (insert/update as an authenticated user) is done by running the iOS app and confirming upserts succeed; this script only inspects policy metadata.

---

## backfill_user_timestamps.sql

This script backfills NULL timestamp values in the `users` table.

### When to Run

Run this script if you have existing users with NULL `created_at` or `updated_at` values that are causing API validation errors.

### How to Run

**Using psql:**
```bash
psql -d your_database_name -f scripts/backfill_user_timestamps.sql
```

**Using Python with SQLAlchemy:**
```python
from app.db.session import engine
with engine.connect() as conn:
    with open('scripts/backfill_user_timestamps.sql') as f:
        conn.execute(text(f.read()))
    conn.commit()
```

**Using a database GUI:**
Copy and paste the SQL commands into your database management tool (pgAdmin, DBeaver, etc.) and execute them.

### What It Does

1. Updates `updated_at` to use `created_at` if available, otherwise `NOW()`
2. Updates `created_at` to use `updated_at` if available, otherwise `NOW()` (safety check)
3. Verifies that no NULL values remain

### Notes

- The User model already has `server_default=func.now()` and `onupdate=func.now()` configured
- This script is only needed to fix existing data that was created before these defaults were enforced
- After running this script, all new users will automatically get timestamps from the database defaults

