"""Production verification SQL — run via:
docker exec -i nexacare-backend-db-1 mysql -unexauser -pnexa123 nexacare < scripts/verify_voice_schema.sql
"""

SELECT 'alembic_version' AS check_name, version_num AS value FROM alembic_version;

SELECT 'phase1_tables' AS check_name, COUNT(*) AS value
FROM information_schema.tables
WHERE table_schema = 'nexacare'
  AND table_name IN (
    'hospital_voice_configs',
    'hospital_faqs',
    'hospital_policies',
    'hospital_voice_documents',
    'voice_callback_tickets'
  );

SELECT 'preferred_language' AS check_name, COLUMN_NAME AS value
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'nexacare' AND TABLE_NAME = 'patients' AND COLUMN_NAME = 'preferred_language';

SELECT 'voice_calls.patient_id_nullable' AS check_name, IS_NULLABLE AS value
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'nexacare' AND TABLE_NAME = 'voice_calls' AND COLUMN_NAME = 'patient_id';

SELECT 'fk' AS check_name,
       CONCAT(TABLE_NAME, '.', COLUMN_NAME, '->', REFERENCED_TABLE_NAME) AS value
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = 'nexacare'
  AND TABLE_NAME IN (
    'hospital_voice_configs',
    'hospital_faqs',
    'hospital_policies',
    'hospital_voice_documents',
    'voice_callback_tickets',
    'voice_calls'
  )
  AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, COLUMN_NAME;

SELECT 'indexes' AS check_name,
       CONCAT(TABLE_NAME, '.', INDEX_NAME, '(', COLUMN_NAME, ')') AS value
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'nexacare'
  AND TABLE_NAME IN (
    'hospital_voice_configs',
    'hospital_faqs',
    'voice_callback_tickets',
    'voice_calls'
  )
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
