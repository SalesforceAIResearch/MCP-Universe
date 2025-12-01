"""
Shared Vector Database Setup Utilities

This module provides utilities for setting up a complete PostgreSQL database
with pgvector extension and sample RAG-related tables with vector data.
Used by all vector database tasks.
"""

import os
import logging
import psycopg2
import json
import random
import numpy as np
from typing import List

logger = logging.getLogger(__name__)

def get_connection_params():
    """Get database connection parameters from environment variables."""
    return {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'user': os.getenv('POSTGRES_USERNAME', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'password'),
        'database': os.getenv('POSTGRES_DATABASE', 'postgres')
    }


def generate_mock_embedding(dimensions: int = 1536) -> List[float]:
    """Generate a mock embedding vector with specified dimensions."""
    # Generate random values between -1 and 1, then normalize
    vector = np.random.uniform(-1, 1, dimensions)
    # Normalize to unit vector (common practice for embeddings)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector.tolist()


def create_vector_extension():
    """Create the pgvector extension."""
    conn_params = get_connection_params()

    try:
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = True

        with conn.cursor() as cur:
            logger.info("Creating pgvector extension...")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            logger.info("pgvector extension created successfully")

        conn.close()

    except psycopg2.Error as e:
        logger.error(f"Failed to create pgvector extension: {e}")
        raise


def create_vector_tables():
    """Create sample tables with vector columns for RAG applications."""
    conn_params = get_connection_params()

    try:
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = True

        with conn.cursor() as cur:
            logger.info("Creating vector database tables...")

            # Create documents table for document embeddings
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_url TEXT,
                    document_type VARCHAR(50) DEFAULT 'article',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    word_count INTEGER,
                    embedding vector(1536)
                );
            """)

            # Create chunks table for document chunks (common in RAG)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    chunk_size INTEGER,
                    overlap_size INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    embedding vector(1536)
                );
            """)

            # Create queries table for storing user queries and their embeddings
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_queries (
                    id SERIAL PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    user_id VARCHAR(100),
                    session_id VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    response_time_ms INTEGER,
                    embedding vector(1536)
                );
            """)

            # Create embeddings metadata table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS embedding_models (
                    id SERIAL PRIMARY KEY,
                    model_name VARCHAR(100) NOT NULL UNIQUE,
                    provider VARCHAR(50) NOT NULL,
                    dimensions INTEGER NOT NULL,
                    max_tokens INTEGER,
                    cost_per_token DECIMAL(10, 8),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """)

            # Create knowledge base table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id SERIAL PRIMARY KEY,
                    kb_name VARCHAR(100) NOT NULL,
                    description TEXT,
                    domain VARCHAR(50),
                    language VARCHAR(10) DEFAULT 'en',
                    total_documents INTEGER DEFAULT 0,
                    total_chunks INTEGER DEFAULT 0,
                    total_storage_mb DECIMAL(10, 2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create similarity search results cache
            cur.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    id SERIAL PRIMARY KEY,
                    query_hash VARCHAR(64) NOT NULL,
                    query_text TEXT NOT NULL,
                    results_json JSONB,
                    result_count INTEGER,
                    search_time_ms INTEGER,
                    similarity_threshold DECIMAL(4, 3),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                );
            """)

            logger.info("Vector database tables created successfully")

        conn.close()

    except psycopg2.Error as e:
        logger.error(f"Failed to create vector tables: {e}")
        raise


def create_vector_indexes():
    """Create indexes for vector columns and other frequently queried fields."""
    conn_params = get_connection_params()

    try:
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = True

        with conn.cursor() as cur:
            logger.info("Creating vector indexes...")

            # Vector indexes using HNSW (Hierarchical Navigable Small World)
            indexes = [
                ("documents_embedding_idx", "documents", "embedding", "hnsw"),
                ("chunks_embedding_idx", "document_chunks", "embedding", "hnsw"),
                ("queries_embedding_idx", "user_queries", "embedding", "hnsw"),
            ]

            for idx_name, table_name, column_name, method in indexes:
                try:
                    if method == "hnsw":
                        cur.execute(f"""
                            CREATE INDEX IF NOT EXISTS {idx_name}
                            ON {table_name} USING hnsw ({column_name} vector_cosine_ops);
                        """)
                    else:
                        cur.execute(f"""
                            CREATE INDEX IF NOT EXISTS {idx_name}
                            ON {table_name} USING ivfflat ({column_name} vector_cosine_ops) WITH (lists = 100);
                        """)
                    logger.info(f"Created index {idx_name} on {table_name}")
                except psycopg2.Error as e:
                    logger.warning(f"Could not create {method} index {idx_name}: {e}")
                    # Try with IVFFlat as fallback
                    if method == "hnsw":
                        try:
                            cur.execute(f"""
                                CREATE INDEX IF NOT EXISTS {idx_name}_ivf
                                ON {table_name} USING ivfflat ({column_name} vector_cosine_ops) WITH (lists = 100);
                            """)
                            logger.info(f"Created fallback IVFFlat index {idx_name}_ivf on {table_name}")
                        except psycopg2.Error as e2:
                            logger.warning(f"Could not create fallback index: {e2}")

            # Regular indexes for performance
            regular_indexes = [
                ("documents_title_idx", "documents", "title"),
                ("documents_type_idx", "documents", "document_type"),
                ("documents_created_idx", "documents", "created_at"),
                ("chunks_doc_id_idx", "document_chunks", "document_id"),
                ("chunks_index_idx", "document_chunks", "chunk_index"),
                ("queries_user_idx", "user_queries", "user_id"),
                ("queries_created_idx", "user_queries", "created_at"),
                ("cache_hash_idx", "search_cache", "query_hash"),
                ("cache_expires_idx", "search_cache", "expires_at"),
            ]

            for idx_name, table_name, column_name in regular_indexes:
                try:
                    cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({column_name});")
                    logger.debug(f"Created regular index {idx_name}")
                except psycopg2.Error as e:
                    logger.warning(f"Could not create regular index {idx_name}: {e}")

            logger.info("Vector indexes created successfully")

        conn.close()

    except psycopg2.Error as e:
        logger.error(f"Failed to create vector indexes: {e}")
        raise


def insert_sample_data():
    """Insert sample data into vector tables."""
    conn_params = get_connection_params()

    try:
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = True

        with conn.cursor() as cur:
            logger.info("Inserting sample data...")

            # Insert embedding models
            embedding_models = [
                ('text-embedding-3-small', 'OpenAI', 1536, 8192, 0.00000002, True),
                ('text-embedding-3-large', 'OpenAI', 3072, 8192, 0.00000013, True),
                ('text-embedding-ada-002', 'OpenAI', 1536, 8192, 0.00000010, False),
                ('all-MiniLM-L6-v2', 'Sentence-Transformers', 384, 512, 0.0, True),
                ('all-mpnet-base-v2', 'Sentence-Transformers', 768, 514, 0.0, True),
            ]

            for model_data in embedding_models:
                cur.execute("""
                    INSERT INTO embedding_models (model_name, provider, dimensions, max_tokens, cost_per_token, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (model_name) DO NOTHING;
                """, model_data)

            # Insert knowledge bases
            knowledge_bases = [
                ('Technical Documentation', 'Software engineering and API documentation', 'technology'),
                ('Research Papers', 'Academic papers and research publications', 'research'),
                ('Customer Support', 'FAQ and troubleshooting guides', 'support'),
                ('Product Catalog', 'Product descriptions and specifications', 'commerce'),
                ('Legal Documents', 'Contracts, policies, and legal texts', 'legal'),
            ]

            kb_ids = []
            for kb_data in knowledge_bases:
                cur.execute("""
                    INSERT INTO knowledge_base (kb_name, description, domain, total_documents, total_chunks, total_storage_mb)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, kb_data + (random.randint(50, 500), random.randint(200, 2000), round(random.uniform(10.5, 250.8), 2)))
                kb_ids.append(cur.fetchone()[0])

            # Insert sample documents
            sample_documents = [
                ("PostgreSQL Performance Tuning", "Comprehensive guide to optimizing PostgreSQL database performance including indexing strategies, query optimization, and configuration tuning.", "https://example.com/pg-performance", "technical_guide"),
                ("Vector Similarity Search", "Understanding vector embeddings and similarity search algorithms for AI applications and recommendation systems.", "https://example.com/vector-search", "technical_guide"),
                ("RAG Implementation Best Practices", "Best practices for implementing Retrieval-Augmented Generation systems using vector databases and large language models.", "https://example.com/rag-practices", "best_practices"),
                ("Database Security Guidelines", "Security considerations and implementation guidelines for PostgreSQL databases in production environments.", "https://example.com/db-security", "security_guide"),
                ("Machine Learning with SQL", "Integrating machine learning workflows with SQL databases and leveraging database extensions for AI applications.", "https://example.com/ml-sql", "tutorial"),
                ("API Documentation Standards", "Standards and best practices for creating comprehensive and user-friendly API documentation.", "https://example.com/api-docs", "documentation"),
                ("Microservices Architecture", "Design patterns and implementation strategies for microservices architecture in modern applications.", "https://example.com/microservices", "architecture_guide"),
                ("Data Pipeline Optimization", "Optimizing data processing pipelines for scalability, reliability, and performance in enterprise environments.", "https://example.com/data-pipelines", "optimization_guide"),
                ("Cloud Database Migration", "Step-by-step guide for migrating on-premises databases to cloud infrastructure with minimal downtime.", "https://example.com/cloud-migration", "migration_guide"),
                ("NoSQL vs SQL Comparison", "Detailed comparison of NoSQL and SQL databases, including use cases, performance characteristics, and selection criteria.", "https://example.com/nosql-sql", "comparison_guide"),
            ]

            doc_ids = []
            for title, content, url, doc_type in sample_documents:
                embedding = generate_mock_embedding(1536)
                word_count = len(content.split())

                cur.execute("""
                    INSERT INTO documents (title, content, source_url, document_type, word_count, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                """, (title, content, url, doc_type, word_count, embedding))
                doc_ids.append(cur.fetchone()[0])

            # Insert document chunks
            chunk_count = 0
            for doc_id in doc_ids:
                # Generate 3-7 chunks per document
                num_chunks = random.randint(3, 7)
                for chunk_idx in range(num_chunks):
                    chunk_text = f"This is chunk {chunk_idx + 1} of document {doc_id}. " + \
                               "It contains relevant information that would be useful for similarity search and RAG applications. " + \
                               "The content includes technical details, examples, and best practices."
                    chunk_size = len(chunk_text)
                    overlap_size = random.randint(20, 50) if chunk_idx > 0 else 0
                    embedding = generate_mock_embedding(1536)

                    cur.execute("""
                        INSERT INTO document_chunks (document_id, chunk_index, chunk_text, chunk_size, overlap_size, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """, (doc_id, chunk_idx, chunk_text, chunk_size, overlap_size, embedding))
                    chunk_count += 1

            # Insert sample user queries
            sample_queries = [
                ("How to optimize PostgreSQL performance?", "user123", "session_abc1"),
                ("What are vector embeddings?", "user456", "session_def2"),
                ("Best practices for RAG implementation", "user789", "session_ghi3"),
                ("Database security checklist", "user123", "session_abc2"),
                ("Machine learning with databases", "user456", "session_def3"),
                ("API documentation examples", "user321", "session_jkl1"),
                ("Microservices design patterns", "user654", "session_mno2"),
                ("Data pipeline best practices", "user987", "session_pqr3"),
                ("Cloud migration strategies", "user111", "session_stu4"),
                ("NoSQL vs SQL databases", "user222", "session_vwx5"),
            ]

            for query_text, user_id, session_id in sample_queries:
                embedding = generate_mock_embedding(1536)
                response_time = random.randint(50, 500)

                cur.execute("""
                    INSERT INTO user_queries (query_text, user_id, session_id, response_time_ms, embedding)
                    VALUES (%s, %s, %s, %s, %s);
                """, (query_text, user_id, session_id, response_time, embedding))

            # Insert some search cache entries
            for i in range(5):
                query_hash = f"hash_{random.randint(100000, 999999)}"
                query_text = f"Sample cached query {i + 1}"
                results = [{"doc_id": random.randint(1, len(doc_ids)), "similarity": round(random.uniform(0.7, 0.95), 3)} for _ in range(3)]
                result_count = len(results)
                search_time = random.randint(10, 100)
                threshold = round(random.uniform(0.6, 0.8), 3)

                cur.execute("""
                    INSERT INTO search_cache (query_hash, query_text, results_json, result_count, search_time_ms, similarity_threshold)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (query_hash, query_text, json.dumps(results), result_count, search_time, threshold))

            logger.info(f"Sample data inserted successfully:")
            logger.info(f"   {len(sample_documents)} documents")
            logger.info(f"   {chunk_count} document chunks")
            logger.info(f"   {len(sample_queries)} user queries")
            logger.info(f"   {len(embedding_models)} embedding models")
            logger.info(f"   {len(knowledge_bases)} knowledge bases")

        conn.close()

    except psycopg2.Error as e:
        logger.error(f"Failed to insert sample data: {e}")
        raise


def verify_vector_setup():
    """Verify that the vector database was set up correctly."""
    conn_params = get_connection_params()

    try:
        conn = psycopg2.connect(**conn_params)

        with conn.cursor() as cur:
            logger.info("Verifying vector database setup...")

            # Check extension
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
            if cur.fetchone():
                logger.info("pgvector extension is installed")
            else:
                logger.error("pgvector extension not found")
                return False

            # Check tables and record counts
            tables_to_check = [
                'documents', 'document_chunks', 'user_queries',
                'embedding_models', 'knowledge_base', 'search_cache'
            ]

            table_counts = {}
            for table in tables_to_check:
                cur.execute(f'SELECT COUNT(*) FROM {table}')
                count = cur.fetchone()[0]
                table_counts[table] = count
                logger.info(f"Table {table}: {count} records")

            # Check vector columns
            cur.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE data_type = 'USER-DEFINED'
                AND udt_name = 'vector'
                ORDER BY table_name, column_name;
            """)

            vector_columns = cur.fetchall()
            logger.info(f"Found {len(vector_columns)} vector columns:")
            for table, column, dtype in vector_columns:
                logger.info(f"   {table}.{column} ({dtype})")

            # Check indexes
            cur.execute("""
                SELECT schemaname, tablename, indexname, indexdef
                FROM pg_indexes
                WHERE indexdef LIKE '%vector%' OR indexdef LIKE '%hnsw%' OR indexdef LIKE '%ivfflat%'
                ORDER BY tablename, indexname;
            """)

            vector_indexes = cur.fetchall()
            logger.info(f"Found {len(vector_indexes)} vector indexes:")
            for schema, table, index, definition in vector_indexes:
                logger.info(f"   {index} on {table}")

            # Test a simple vector similarity query
            mock_embedding = generate_mock_embedding(1536)
            cur.execute("""
                SELECT id, title, embedding <-> %s::vector as distance
                FROM documents
                ORDER BY embedding <-> %s::vector
                LIMIT 3;
            """, (mock_embedding, mock_embedding))

            results = cur.fetchall()
            logger.info(f"Vector similarity query returned {len(results)} results")

        conn.close()
        logger.info("Vector database verification completed successfully")
        return table_counts, vector_columns, vector_indexes

    except psycopg2.Error as e:
        logger.error(f"Verification failed: {e}")
        raise


def prepare_vector_environment():
    """Main function to prepare the vector database environment."""
    logger.info("Preparing vector database environment...")

    try:
        # Create pgvector extension
        create_vector_extension()

        # Create vector tables
        create_vector_tables()

        # Insert sample data first
        insert_sample_data()

        # Create indexes after data insertion for better performance
        create_vector_indexes()

        # Verify the setup
        table_counts, vector_columns, vector_indexes = verify_vector_setup()

        logger.info("Vector database environment prepared successfully!")
        logger.info(f"Total tables created: {len(table_counts)}")
        logger.info(f"Total vector columns: {len(vector_columns)}")
        logger.info(f"Total vector indexes: {len(vector_indexes)}")

        return {
            'table_counts': table_counts,
            'vector_columns': vector_columns,
            'vector_indexes': vector_indexes
        }

    except Exception as e:
        logger.error(f"Failed to prepare vector environment: {e}")
        raise


if __name__ == "__main__":
    # Allow running this module directly for testing
    logging.basicConfig(level=logging.INFO)
    prepare_vector_environment()
