#!/usr/bin/env python3

import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys

# Configuration for users and their permissions
USER_CONFIGS = {
    # Active functional users
    'analytics_user': {
        'password': 'analytics123',
        'role': 'Analytics Team',
        'status': 'active'
    },
    'marketing_user': {
        'password': 'marketing123',
        'role': 'Marketing Department',
        'status': 'active'
    },
    'customer_service': {
        'password': 'service123',
        'role': 'Customer Service',
        'status': 'active'
    },
    'finance_user': {
        'password': 'finance123',
        'role': 'Finance Team',
        'status': 'active'
    },
    'product_manager': {
        'password': 'product123',
        'role': 'Product Management',
        'status': 'active'
    },
    'security_auditor': {
        'password': 'security123',
        'role': 'Security Team',
        'status': 'active'
    },
    'developer_user': {
        'password': 'dev123',
        'role': 'Development Team',
        'status': 'active'
    },
    'backup_user': {
        'password': 'backup123',
        'role': 'Backup Service',
        'status': 'active'
    },
    # Inactive/dangling users
    'temp_contractor': {
        'password': 'temp123',
        'role': 'Inactive/Temporary',
        'status': 'inactive'
    },
    'old_employee': {
        'password': 'old456',
        'role': 'Inactive/Temporary',
        'status': 'inactive'
    },
    'test_account': {
        'password': 'test789',
        'role': 'Inactive/Temporary',
        'status': 'inactive'
    }
}

# Expected permissions by role (what they SHOULD have)
ROLE_EXPECTED_PERMISSIONS = {
    'Analytics Team': [
        ('user_profiles', 'SELECT'),
        ('user_stat_analysis', 'SELECT'),
        ('product_catalog', 'SELECT'),
        ('order_management', 'SELECT'),
    ],
    'Marketing Department': [
        ('user_profiles', 'SELECT'),
        ('user_stat_analysis', 'SELECT'),
        ('product_catalog', 'SELECT'),
    ],
    'Customer Service': [
        ('user_profiles', 'SELECT'),
        ('user_profiles', 'UPDATE'),
        ('order_management', 'SELECT'),
        ('order_management', 'INSERT'),
        ('order_management', 'UPDATE'),
        ('product_catalog', 'SELECT'),
    ],
    'Finance Team': [
        ('financial_transactions', 'SELECT'),
        ('order_management', 'SELECT'),
        ('user_profiles', 'SELECT'),
    ],
    'Product Management': [
        ('product_catalog', 'SELECT'),
        ('product_catalog', 'INSERT'),
        ('product_catalog', 'UPDATE'),
        ('product_catalog', 'DELETE'),
        ('order_management', 'SELECT'),
        ('user_stat_analysis', 'SELECT'),
    ],
    'Security Team': [
        ('audit_logs', 'SELECT'),
        ('user_credentials', 'SELECT'),
        ('user_profiles', 'SELECT'),
    ],
    'Development Team': [
        ('user_profiles', 'SELECT'),
        ('product_catalog', 'SELECT'),
    ],
    'Backup Service': [
        ('user_profiles', 'SELECT'),
        ('product_catalog', 'SELECT'),
        ('order_management', 'SELECT'),
        ('financial_transactions', 'SELECT'),
        ('user_stat_analysis', 'SELECT'),
        ('audit_logs', 'SELECT'),
        ('user_credentials', 'SELECT'),
    ],
}

# Excessive permissions that will be granted but should be flagged as security issues
EXCESSIVE_PERMISSIONS = [
    # Users getting financial access they shouldn't have
    ('analytics_user', 'financial_transactions', 'SELECT'),
    ('marketing_user', 'financial_transactions', 'SELECT'),
    ('product_manager', 'financial_transactions', 'SELECT'),

    # Security risks - credential access
    ('customer_service', 'user_credentials', 'SELECT'),
    ('developer_user', 'user_credentials', 'SELECT'),

    # Excessive privileges
    ('security_auditor', 'financial_transactions', 'UPDATE'),
    ('developer_user', 'order_management', 'UPDATE'),
    ('backup_user', 'product_catalog', 'DELETE'),  # Backup should be read-only

    # Inactive users with permissions they shouldn't have
    ('temp_contractor', 'product_catalog', 'SELECT'),
    ('temp_contractor', 'user_profiles', 'SELECT'),
    ('old_employee', 'audit_logs', 'SELECT'),
    ('old_employee', 'user_stat_analysis', 'UPDATE'),
    ('test_account', 'user_profiles', 'SELECT'),
]

# Permissions to revoke to create "missing permission" findings
PERMISSIONS_TO_REVOKE = [
    ('analytics_user', 'user_profiles', 'SELECT'),
    ('analytics_user', 'order_management', 'SELECT'),
    ('analytics_user', 'product_catalog', 'SELECT'),
    ('marketing_user', 'product_catalog', 'SELECT'),
    ('finance_user', 'user_profiles', 'SELECT'),
    ('developer_user', 'product_catalog', 'SELECT'),
    ('customer_service', 'product_catalog', 'SELECT'),
    ('security_auditor', 'audit_logs', 'SELECT'),
    ('product_manager', 'user_stat_analysis', 'SELECT'),
    ('backup_user', 'order_management', 'SELECT'),
    ('backup_user', 'financial_transactions', 'SELECT'),
    ('backup_user', 'user_stat_analysis', 'SELECT'),
    ('backup_user', 'user_credentials', 'SELECT'),
]

def create_business_tables(cur):
    """Create all business tables"""

    tables = [
        ('user_profiles', """
            DROP TABLE IF EXISTS user_profiles CASCADE;
            CREATE TABLE user_profiles (
                user_id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                phone VARCHAR(20),
                address TEXT,
                city VARCHAR(50),
                state VARCHAR(2),
                zip_code VARCHAR(10),
                date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT true,
                profile_picture_url TEXT,
                bio TEXT
            );
        """),

        ('user_credentials', """
            DROP TABLE IF EXISTS user_credentials CASCADE;
            CREATE TABLE user_credentials (
                credential_id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                password_hash VARCHAR(255) NOT NULL,
                salt VARCHAR(100) NOT NULL,
                login_attempts INTEGER DEFAULT 0,
                last_login TIMESTAMP,
                password_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                password_expires TIMESTAMP,
                is_locked BOOLEAN DEFAULT false,
                two_factor_enabled BOOLEAN DEFAULT false,
                two_factor_secret VARCHAR(32),
                backup_codes TEXT[],
                security_questions JSONB
            );
        """),

        ('user_stat_analysis', """
            DROP TABLE IF EXISTS user_stat_analysis CASCADE;
            CREATE TABLE user_stat_analysis (
                analysis_id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES user_profiles(user_id) ON DELETE CASCADE,
                session_id VARCHAR(100),
                page_views INTEGER DEFAULT 0,
                time_spent_minutes INTEGER DEFAULT 0,
                actions_performed JSONB,
                device_info JSONB,
                ip_address INET,
                location_data JSONB,
                referrer_url TEXT,
                conversion_events JSONB,
                analysis_date DATE DEFAULT CURRENT_DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """),

        ('product_catalog', """
            DROP TABLE IF EXISTS product_catalog CASCADE;
            CREATE TABLE product_catalog (
                product_id SERIAL PRIMARY KEY,
                product_name VARCHAR(100) NOT NULL,
                description TEXT,
                category VARCHAR(50),
                price DECIMAL(10,2) NOT NULL,
                cost DECIMAL(10,2),
                sku VARCHAR(50) UNIQUE,
                inventory_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                supplier_info JSONB,
                weight_kg DECIMAL(6,2),
                dimensions JSONB
            );
        """),

        ('order_management', """
            DROP TABLE IF EXISTS order_management CASCADE;
            CREATE TABLE order_management (
                order_id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES user_profiles(user_id),
                order_number VARCHAR(50) UNIQUE NOT NULL,
                order_status VARCHAR(20) DEFAULT 'pending',
                total_amount DECIMAL(12,2) NOT NULL,
                tax_amount DECIMAL(12,2),
                shipping_amount DECIMAL(12,2),
                discount_amount DECIMAL(12,2) DEFAULT 0,
                payment_method VARCHAR(50),
                payment_status VARCHAR(20) DEFAULT 'pending',
                shipping_address JSONB,
                billing_address JSONB,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                shipped_date TIMESTAMP,
                delivered_date TIMESTAMP,
                tracking_number VARCHAR(100)
            );
        """),

        ('financial_transactions', """
            DROP TABLE IF EXISTS financial_transactions CASCADE;
            CREATE TABLE financial_transactions (
                transaction_id SERIAL PRIMARY KEY,
                order_id INTEGER REFERENCES order_management(order_id),
                user_id INTEGER REFERENCES user_profiles(user_id),
                transaction_type VARCHAR(20) NOT NULL,
                amount DECIMAL(12,2) NOT NULL,
                currency VARCHAR(3) DEFAULT 'USD',
                payment_gateway VARCHAR(50),
                gateway_transaction_id VARCHAR(100),
                credit_card_last_four CHAR(4),
                bank_account_last_four CHAR(4),
                transaction_status VARCHAR(20) DEFAULT 'pending',
                processed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fee_amount DECIMAL(8,2),
                refund_amount DECIMAL(12,2) DEFAULT 0,
                notes TEXT
            );
        """),

        ('audit_logs', """
            DROP TABLE IF EXISTS audit_logs CASCADE;
            CREATE TABLE audit_logs (
                log_id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES user_profiles(user_id),
                action_type VARCHAR(50) NOT NULL,
                table_name VARCHAR(50),
                record_id INTEGER,
                old_values JSONB,
                new_values JSONB,
                ip_address INET,
                user_agent TEXT,
                session_id VARCHAR(100),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN DEFAULT true,
                error_message TEXT
            );
        """)
    ]

    for table_name, sql in tables:
        cur.execute(sql)

def create_users(cur):
    """Create PostgreSQL users from configuration"""
    for username, config in USER_CONFIGS.items():
        cur.execute(f"CREATE USER {username} WITH PASSWORD %s;", (config['password'],))

def grant_expected_permissions(cur):
    """Grant expected permissions to users based on their roles"""
    for username, config in USER_CONFIGS.items():
        if config['status'] == 'active':
            role = config['role']
            permissions = ROLE_EXPECTED_PERMISSIONS.get(role, [])
            for table_name, privilege in permissions:
                cur.execute(f"GRANT {privilege} ON {table_name} TO {username};")

def grant_excessive_permissions(cur):
    """Grant excessive permissions that should be flagged as security issues"""
    for username, table_name, privilege in EXCESSIVE_PERMISSIONS:
        cur.execute(f"GRANT {privilege} ON {table_name} TO {username};")

def revoke_permissions(cur):
    """Revoke specific permissions to create missing permission findings"""
    for username, table_name, privilege in PERMISSIONS_TO_REVOKE:
        cur.execute(f"REVOKE {privilege} ON {table_name} FROM {username};")

def grant_sequence_permissions(cur):
    """Grant sequence permissions for users that need them"""
    users_needing_sequences = ['customer_service', 'product_manager']
    for username in users_needing_sequences:
        cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {username};")

def setup_security_environment():
    """
    Set up a security-focused PostgreSQL environment with business tables and users with various permissions.
    Creates a scenario where some users have dangling or insufficient permissions for realistic security analysis.
    """

    # Database connection parameters from environment
    db_params = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'user': os.getenv('POSTGRES_USERNAME', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'password'),
        'database': os.getenv('POSTGRES_DATABASE', 'postgres')
    }

    postgres_params = db_params.copy()
    postgres_params['database'] = 'postgres'

    try:
        conn_postgres = psycopg2.connect(**postgres_params)
        conn_postgres.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur_postgres = conn_postgres.cursor()

        current_db = db_params['database']
        cur_postgres.execute("SELECT datname FROM pg_database WHERE datname LIKE %s AND datname != %s;", ('%user_permission_audit%', current_db))
        audit_databases = cur_postgres.fetchall()

        if audit_databases:
            for db_row in audit_databases:
                db_name = db_row[0]
                try:
                    cur_postgres.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s;", (db_name,))
                    cur_postgres.execute(f"DROP DATABASE IF EXISTS {db_name};")
                    print(f"Dropped database: {db_name}")
                except Exception as e:
                    print(f"Warning: Could not drop database {db_name}: {e}")

        # Clean up existing users
        for username in USER_CONFIGS.keys():
            try:
                cur_postgres.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s;", (username,))
                cur_postgres.execute(f"DROP USER IF EXISTS {username};")
            except Exception as e:
                print(f"Warning: Could not drop user {username}: {e}")

        cur_postgres.close()
        conn_postgres.close()

    except Exception as e:
        print(f"Warning: Could not clean up users: {e}")

    try:
        conn = psycopg2.connect(**db_params)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        print("Setting up security audit environment...")

        # Create business tables with realistic structure
        create_business_tables(cur)
        print("Created 7 business tables")

        # Create users
        create_users(cur)
        active_count = len([u for u in USER_CONFIGS.values() if u['status'] == 'active'])
        inactive_count = len([u for u in USER_CONFIGS.values() if u['status'] == 'inactive'])
        print(f"Created {len(USER_CONFIGS)} users ({active_count} functional, {inactive_count} dangling)")

        # Grant expected permissions
        grant_expected_permissions(cur)

        # Grant excessive permissions that will be flagged as issues
        grant_excessive_permissions(cur)

        print("Granted initial permissions")

        # Revoke specific permissions to create missing permission findings
        revoke_permissions(cur)

        # Grant sequence permissions where needed
        grant_sequence_permissions(cur)

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error setting up environment: {e}")
        sys.exit(1)


def prepare_environment():
    """Unified entry point for environment preparation (called by mcpuniverse)."""
    setup_security_environment()


if __name__ == "__main__":
    setup_security_environment()
