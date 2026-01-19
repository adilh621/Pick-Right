# Database Scripts

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

