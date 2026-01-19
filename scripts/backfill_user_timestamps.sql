-- Backfill NULL timestamps in users table
-- This script fixes existing NULL values in created_at and updated_at columns
-- Run this script once to fix existing data before enforcing NOT NULL constraints

-- Backfill updated_at where NULL:
-- Use created_at if available, otherwise use NOW()
UPDATE users 
SET updated_at = COALESCE(updated_at, created_at, NOW()) 
WHERE updated_at IS NULL;

-- Backfill created_at where NULL (shouldn't happen, but just in case):
UPDATE users 
SET created_at = COALESCE(created_at, updated_at, NOW()) 
WHERE created_at IS NULL;

-- Verify no NULLs remain (should return 0 rows)
SELECT COUNT(*) as null_updated_at_count 
FROM users 
WHERE updated_at IS NULL;

SELECT COUNT(*) as null_created_at_count 
FROM users 
WHERE created_at IS NULL;

