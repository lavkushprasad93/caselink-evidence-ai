-- Restricted application role; run as the database owner after migrations.
-- Re-run after migrations that add tables so the role receives their privileges.
--
-- Example:
--   psql -h localhost -p 5434 -U <owner> -d caselink_evidence_ai \
--     -v app_password='choose-a-strong-password' -f infra/postgres/roles.sql
--
-- Keep the owner URL in MIGRATION_DATABASE_URL and use caselink_app in DATABASE_URL.
-- Do not run this against a database unless you intend to create/update this role.

SELECT 'CREATE ROLE caselink_app LOGIN' WHERE NOT EXISTS (
  SELECT FROM pg_roles WHERE rolname = 'caselink_app'
) \gexec

ALTER ROLE caselink_app
  PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;

GRANT CONNECT ON DATABASE :"DBNAME" TO caselink_app;
GRANT USAGE ON SCHEMA public TO caselink_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO caselink_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO caselink_app;

REVOKE UPDATE, DELETE, TRUNCATE ON audit_log, provenance_event FROM caselink_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM caselink_app;
