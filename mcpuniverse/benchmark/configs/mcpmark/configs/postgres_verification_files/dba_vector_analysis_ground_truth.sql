-- Ground Truth Data for Vector Database Analysis Task
-- This defines the exact expected results that candidates should discover and report

/*
================================================================================
EXPECTED VECTOR DATABASE STRUCTURE (created by vectors_setup.py)
================================================================================

Tables with Vector Columns:
1. documents.embedding (vector(1536))
2. document_chunks.embedding (vector(1536))
3. user_queries.embedding (vector(1536))

Vector Indexes:
1. documents_embedding_idx (HNSW on documents.embedding)
2. chunks_embedding_idx (HNSW on document_chunks.embedding)
3. queries_embedding_idx (HNSW on user_queries.embedding)

Expected Data Counts:
- documents: 10 records
- document_chunks: ~40-70 records (3-7 chunks per document)
- user_queries: 10 records
- embedding_models: 5 records (metadata)
- knowledge_base: 5 records (metadata)
- search_cache: 5 records (metadata)

================================================================================
DEFINITIVE GROUND TRUTH VERIFICATION DATA
================================================================================
*/

BEGIN;

-- Create expected analysis result structure
CREATE TABLE IF NOT EXISTS expected_vector_column_inventory (
    table_schema VARCHAR(50) DEFAULT 'public',
    table_name VARCHAR(100),
    column_name VARCHAR(100),
    vector_dimensions INTEGER,
    data_type VARCHAR(50) DEFAULT 'USER-DEFINED',
    has_constraints BOOLEAN DEFAULT false,
    min_estimated_rows BIGINT
);

-- Insert expected vector column inventory
INSERT INTO expected_vector_column_inventory (table_name, column_name, vector_dimensions, min_estimated_rows) VALUES
('documents', 'embedding', 1536, 10),
('document_chunks', 'embedding', 1536, 30),
('user_queries', 'embedding', 1536, 10);

-- Create expected storage analysis structure
CREATE TABLE IF NOT EXISTS expected_vector_storage_analysis (
    table_name VARCHAR(100),
    has_vector_data BOOLEAN,
    min_row_count BIGINT,
    vector_column_exists BOOLEAN,
    should_have_storage_metrics BOOLEAN DEFAULT true
);

-- Insert expected storage analysis
INSERT INTO expected_vector_storage_analysis (table_name, has_vector_data, min_row_count, vector_column_exists) VALUES
('documents', true, 10, true),
('document_chunks', true, 30, true),
('user_queries', true, 10, true),
('embedding_models', false, 5, false),
('knowledge_base', false, 5, false),
('search_cache', false, 5, false);

-- Create expected index analysis structure
CREATE TABLE IF NOT EXISTS expected_vector_index_analysis (
    index_name_pattern VARCHAR(100),
    table_name VARCHAR(100),
    column_name VARCHAR(100),
    expected_index_type VARCHAR(50),
    should_exist BOOLEAN DEFAULT true
);

-- Insert expected vector index analysis
INSERT INTO expected_vector_index_analysis (index_name_pattern, table_name, column_name, expected_index_type) VALUES
('%documents%embedding%', 'documents', 'embedding', 'hnsw'),
('%chunks%embedding%', 'document_chunks', 'embedding', 'hnsw'),
('%queries%embedding%', 'user_queries', 'embedding', 'hnsw');

-- Create storage analysis table
CREATE TABLE vector_storage_analysis (
    table_name VARCHAR(100),
    total_size_bytes BIGINT,
    vector_data_bytes BIGINT,
    regular_data_bytes BIGINT,
    vector_storage_pct NUMERIC(5,2),
    row_count BIGINT,
    avg_vector_size_bytes INTEGER
);

-- Populate storage analysis with actual storage metrics
DO $$
DECLARE
    rec RECORD;
    total_size BIGINT;
    row_cnt BIGINT;
    vector_size INTEGER := 1536 * 4; -- 1536 dimensions * 4 bytes per float
BEGIN
    FOR rec IN SELECT tablename FROM pg_tables WHERE tablename IN ('documents', 'document_chunks', 'user_queries') LOOP
        EXECUTE format('SELECT COUNT(*) FROM %I', rec.tablename) INTO row_cnt;
        SELECT pg_total_relation_size(format('public.%I', rec.tablename)) INTO total_size;

        INSERT INTO vector_storage_analysis (
            table_name, total_size_bytes, row_count, avg_vector_size_bytes,
            vector_data_bytes, regular_data_bytes, vector_storage_pct
        ) VALUES (
            rec.tablename,
            total_size,
            row_cnt,
            vector_size,
            row_cnt * vector_size,
            GREATEST(total_size - (row_cnt * vector_size), 0),
            ROUND((row_cnt * vector_size * 100.0) / NULLIF(total_size, 0), 2)
        );
    END LOOP;
END $$;

-- Create index analysis table
CREATE TABLE vector_index_analysis (
    index_name VARCHAR(100),
    table_name VARCHAR(100),
    column_name VARCHAR(100),
    index_type VARCHAR(50),
    index_size_bytes BIGINT,
    index_parameters TEXT,
    is_valid BOOLEAN
);

-- Populate index analysis with actual vector indexes
INSERT INTO vector_index_analysis (index_name, table_name, column_name, index_type, index_size_bytes, is_valid)
SELECT
    i.indexname as index_name,
    i.tablename as table_name,
    'embedding' as column_name, -- Known from our setup
    CASE
        WHEN i.indexdef ILIKE '%hnsw%' THEN 'hnsw'
        WHEN i.indexdef ILIKE '%ivfflat%' THEN 'ivfflat'
        ELSE 'unknown'
    END as index_type,
    pg_relation_size(format('public.%I', i.indexname)) as index_size_bytes,
    true as is_valid
FROM pg_indexes i
WHERE (i.indexdef ILIKE '%vector%' OR i.indexdef ILIKE '%hnsw%' OR i.indexdef ILIKE '%ivfflat%')
AND i.tablename IN ('documents', 'document_chunks', 'user_queries')
ORDER BY i.tablename, i.indexname;

-- Create data quality analysis table
CREATE TABLE vector_data_quality (
    table_name VARCHAR(100),
    column_name VARCHAR(100),
    quality_check_type VARCHAR(50),
    total_records BIGINT,
    issue_count BIGINT,
    quality_status VARCHAR(20),
    details TEXT
);

-- Populate data quality analysis with actual checks
DO $$
DECLARE
    rec RECORD;
    total_cnt BIGINT;
    null_cnt BIGINT;
BEGIN
    FOR rec IN SELECT tablename FROM pg_tables WHERE tablename IN ('documents', 'document_chunks', 'user_queries') LOOP
        -- Count total records
        EXECUTE format('SELECT COUNT(*) FROM %I', rec.tablename) INTO total_cnt;

        -- Count NULL vectors
        EXECUTE format('SELECT COUNT(*) FROM %I WHERE embedding IS NULL', rec.tablename) INTO null_cnt;

        -- Insert NULL_CHECK result
        INSERT INTO vector_data_quality (
            table_name, column_name, quality_check_type,
            total_records, issue_count, quality_status
        ) VALUES (
            rec.tablename, 'embedding', 'NULL_CHECK',
            total_cnt, null_cnt,
            CASE WHEN null_cnt = 0 THEN 'GOOD' ELSE 'WARNING' END
        );

        -- Insert DIMENSION_CHECK result (all vectors in our setup are 1536-dimensional)
        INSERT INTO vector_data_quality (
            table_name, column_name, quality_check_type,
            total_records, issue_count, quality_status
        ) VALUES (
            rec.tablename, 'embedding', 'DIMENSION_CHECK',
            total_cnt - null_cnt, 0, 'GOOD'
        );
    END LOOP;
END $$;

-- ============================================================================
-- GROUND TRUTH IMPLEMENTATION
-- ============================================================================
-- This is the correct analysis implementation that candidates should produce

-- Create vector_analysis_columns table and populate it
CREATE TABLE vector_analysis_columns (
    schema VARCHAR(50),
    table_name VARCHAR(100),
    column_name VARCHAR(100),
    dimensions INTEGER,
    data_type VARCHAR(50),
    has_constraints BOOLEAN,
    rows BIGINT
);

-- Discover and insert vector columns
INSERT INTO vector_analysis_columns (schema, table_name, column_name, dimensions, data_type, has_constraints, rows)
SELECT
    'public' as schema,
    c.table_name,
    c.column_name,
    1536 as dimensions, -- pgvector embedding dimension
    'USER-DEFINED' as data_type,
    false as has_constraints,
    -- Get actual row count using dynamic query
    CASE c.table_name
        WHEN 'documents' THEN (SELECT COUNT(*) FROM documents)
        WHEN 'document_chunks' THEN (SELECT COUNT(*) FROM document_chunks)
        WHEN 'user_queries' THEN (SELECT COUNT(*) FROM user_queries)
        ELSE 0
    END as rows
FROM information_schema.columns c
WHERE c.data_type = 'USER-DEFINED'
AND c.udt_name = 'vector'
ORDER BY c.table_name, c.column_name;

-- Create vector_analysis_storage_consumption table
CREATE TABLE vector_analysis_storage_consumption (
    schema VARCHAR(50),
    table_name VARCHAR(100),
    total_size_bytes BIGINT,
    vector_data_bytes BIGINT,
    regular_data_bytes BIGINT,
    vector_storage_pct NUMERIC(5,2),
    row_count BIGINT
);

-- Populate storage analysis for vector tables
DO $$
DECLARE
    rec RECORD;
    total_size BIGINT;
    row_cnt BIGINT;
    vector_size INTEGER := 1536 * 4; -- 1536 dimensions * 4 bytes per float
BEGIN
    FOR rec IN
        SELECT DISTINCT c.table_name
        FROM information_schema.columns c
        WHERE c.data_type = 'USER-DEFINED'
        AND c.udt_name = 'vector'
    LOOP
        -- Get actual row count
        EXECUTE format('SELECT COUNT(*) FROM %I', rec.table_name) INTO row_cnt;

        -- Get actual table size
        SELECT pg_total_relation_size(format('public.%I', rec.table_name)) INTO total_size;

        -- Insert analysis results
        INSERT INTO vector_analysis_storage_consumption (
            schema, table_name, total_size_bytes, vector_data_bytes,
            regular_data_bytes, vector_storage_pct, row_count
        ) VALUES (
            'public',
            rec.table_name,
            total_size,
            row_cnt * vector_size,
            GREATEST(total_size - (row_cnt * vector_size), 0),
            ROUND((row_cnt * vector_size * 100.0) / NULLIF(total_size, 0), 2),
            row_cnt
        );
    END LOOP;
END $$;

-- Create vector_analysis_indices table
CREATE TABLE vector_analysis_indices (
    schema VARCHAR(50),
    table_name VARCHAR(100),
    column_name VARCHAR(100),
    index_name VARCHAR(100),
    index_type VARCHAR(50),
    index_size_bytes BIGINT
);

-- Populate index analysis for vector indexes
INSERT INTO vector_analysis_indices (schema, table_name, column_name, index_name, index_type, index_size_bytes)
SELECT
    i.schemaname as schema,
    i.tablename as table_name,
    'embedding' as column_name, -- known from our setup
    i.indexname as index_name,
    CASE
        WHEN i.indexdef ILIKE '%hnsw%' THEN 'hnsw'
        WHEN i.indexdef ILIKE '%ivfflat%' THEN 'ivfflat'
        ELSE 'unknown'
    END as index_type,
    pg_relation_size(format('public.%I', i.indexname)) as index_size_bytes
FROM pg_indexes i
WHERE (i.indexdef ILIKE '%hnsw%' OR i.indexdef ILIKE '%ivfflat%')
AND i.tablename IN (
    SELECT DISTINCT table_name
    FROM information_schema.columns
    WHERE data_type = 'USER-DEFINED' AND udt_name = 'vector'
)
ORDER BY i.tablename, i.indexname;

COMMIT;

-- ============================================================================
-- VERIFICATION HELPER QUERIES
-- ============================================================================

-- Query to check actual vector columns in the database
/*
SELECT
    table_schema,
    table_name,
    column_name,
    data_type,
    udt_name
FROM information_schema.columns
WHERE data_type = 'USER-DEFINED'
AND udt_name = 'vector'
ORDER BY table_name, column_name;
*/

-- Query to check actual vector indexes
/*
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE indexdef ILIKE '%vector%'
   OR indexdef ILIKE '%hnsw%'
   OR indexdef ILIKE '%ivfflat%'
ORDER BY tablename, indexname;
*/

-- Query to check table row counts
/*
SELECT
    'documents' as table_name, COUNT(*) as row_count FROM documents
UNION ALL
SELECT
    'document_chunks' as table_name, COUNT(*) as row_count FROM document_chunks
UNION ALL
SELECT
    'user_queries' as table_name, COUNT(*) as row_count FROM user_queries
ORDER BY table_name;
*/

-- Query to check pgvector extension
/*
SELECT extname, extversion
FROM pg_extension
WHERE extname = 'vector';
*/
