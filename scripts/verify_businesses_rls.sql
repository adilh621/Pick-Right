-- Verify RLS policies on public.businesses
-- Requires: PostgreSQL (e.g. Supabase). Run in Supabase SQL Editor or psql against your project DB.
--
-- This script only inspects policies. Full verification (insert/update as authenticated)
-- is done by running the iOS app with anon key + JWT and confirming upserts succeed.

-- 1. Check that RLS is enabled on businesses
SELECT
  relname AS table_name,
  relrowsecurity AS rls_enabled
FROM pg_class
WHERE relname = 'businesses'
  AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public');

-- 2. List all policies on businesses (after migration you should see 3 policies)
SELECT
  policyname,
  cmd AS command,
  permissive,
  roles,
  qual AS using_expression,
  with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename = 'businesses'
ORDER BY policyname;
