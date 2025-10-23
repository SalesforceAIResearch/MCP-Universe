#!/usr/bin/env python3

import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys

def setup_rls_environment():
    """
    Set up a PostgreSQL environment for a social media platform with RLS policies.
    Creates Users, Channels, Posts, Comments, and Channel Moderators for testing RLS implementations.
    """

    # Database connection parameters from environment
    db_params = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'user': os.getenv('POSTGRES_USERNAME', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'password'),
        'database': os.getenv('POSTGRES_DATABASE', 'postgres')
    }

    try:
        conn = psycopg2.connect(**db_params)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # 1. Users Table (with correct field name for verification)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                is_public BOOLEAN DEFAULT false,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✓ Created users table")

        # 2. Channels Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(100) NOT NULL,
                description TEXT,
                is_public BOOLEAN DEFAULT true,
                owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✓ Created channels table")

        # 3. Channel Moderators Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_moderators (
                channel_id UUID REFERENCES channels(id) ON DELETE CASCADE,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (channel_id, user_id)
            );
        """)
        print("✓ Created channel_moderators table")

        # 4. Posts Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                channel_id UUID REFERENCES channels(id) ON DELETE CASCADE,
                author_id UUID REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(200) NOT NULL,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✓ Created posts table")

        # 5. Comments Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                post_id UUID REFERENCES posts(id) ON DELETE CASCADE,
                author_id UUID REFERENCES users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✓ Created comments table")

        # Create helper functions for RLS (matching ground truth expectations)
        cur.execute("""
            -- Function to get current user ID from session context
            CREATE OR REPLACE FUNCTION app_current_user_id()
            RETURNS UUID AS $$
            BEGIN
                RETURN NULLIF(current_setting('app.current_user_id', true), '')::UUID;
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER STABLE PARALLEL SAFE;

            -- Function to check if user owns a channel
            CREATE OR REPLACE FUNCTION is_channel_owner(p_channel_id UUID, p_user_id UUID)
            RETURNS BOOLEAN AS $$
            BEGIN
                RETURN EXISTS (
                    SELECT 1 FROM channels
                    WHERE id = p_channel_id AND owner_id = p_user_id
                );
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER STABLE PARALLEL SAFE;

            -- Function to check if user moderates a channel
            CREATE OR REPLACE FUNCTION is_channel_moderator(p_channel_id UUID, p_user_id UUID)
            RETURNS BOOLEAN AS $$
            BEGIN
                RETURN EXISTS (
                    SELECT 1 FROM channel_moderators
                    WHERE channel_id = p_channel_id AND user_id = p_user_id
                );
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER STABLE PARALLEL SAFE;

            -- Function to check if user can moderate channel (owner OR moderator)
            CREATE OR REPLACE FUNCTION can_moderate_channel(p_channel_id UUID, p_user_id UUID)
            RETURNS BOOLEAN AS $$
            BEGIN
                RETURN is_channel_owner(p_channel_id, p_user_id)
                       OR is_channel_moderator(p_channel_id, p_user_id);
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER STABLE PARALLEL SAFE;
        """)
        print("✓ Created RLS helper functions")

        # Insert sample data
        print("\nInserting sample data...")

        # Sample users (exact UUIDs expected by verification script)
        cur.execute("""
            INSERT INTO users (id, username, email, is_public) VALUES
            ('11111111-1111-1111-1111-111111111111', 'alice', 'alice@example.com', true),
            ('22222222-2222-2222-2222-222222222222', 'bob', 'bob@example.com', true),
            ('33333333-3333-3333-3333-333333333333', 'charlie', 'charlie@example.com', false),
            ('44444444-4444-4444-4444-444444444444', 'diana', 'diana@example.com', true),
            ('55555555-5555-5555-5555-555555555555', 'eve', 'eve@example.com', false)
            ON CONFLICT (id) DO NOTHING;
        """)
        print("✓ Created 5 sample users")

        # Sample channels (exact UUIDs expected by verification script)
        cur.execute("""
            INSERT INTO channels (id, name, description, is_public, owner_id) VALUES
            ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'general', 'General discussion channel', true, '11111111-1111-1111-1111-111111111111'),
            ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'tech-talk', 'Technical discussions', true, '22222222-2222-2222-2222-222222222222'),
            ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'random', 'Random conversations', false, '33333333-3333-3333-3333-333333333333')
            ON CONFLICT (id) DO NOTHING;
        """)
        print("✓ Created 3 sample channels")

        # Sample moderators (exact relationships expected by verification script)
        cur.execute("""
            INSERT INTO channel_moderators (channel_id, user_id) VALUES
            ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '22222222-2222-2222-2222-222222222222'),  -- Bob moderates general
            ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '44444444-4444-4444-4444-444444444444')  -- Diana moderates tech-talk
            ON CONFLICT (channel_id, user_id) DO NOTHING;
        """)
        print("✓ Created sample moderator assignments")

        # Sample posts (exact UUIDs expected by verification script)
        cur.execute("""
            INSERT INTO posts (id, channel_id, author_id, title, content) VALUES
            ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'Welcome to the platform!', 'This is our first post'),
            ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '33333333-3333-3333-3333-333333333333', 'Hello everyone', 'Nice to meet you all'),
            ('ffffffff-ffff-ffff-ffff-ffffffffffff', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'PostgreSQL RLS Tutorial', 'Let''s discuss Row Level Security'),
            ('10101010-1010-1010-1010-101010101010', 'cccccccc-cccc-cccc-cccc-cccccccccccc', '55555555-5555-5555-5555-555555555555', 'Random thoughts', 'Just some random content here')
            ON CONFLICT (id) DO NOTHING;
        """)
        print("✓ Created 4 sample posts")

        # Sample comments (exact UUIDs expected by verification script)
        cur.execute("""
            INSERT INTO comments (id, post_id, author_id, content) VALUES
            ('99999999-9999-9999-9999-999999999999', 'dddddddd-dddd-dddd-dddd-dddddddddddd', '22222222-2222-2222-2222-222222222222', 'Great to have you here!'),
            ('88888888-8888-8888-8888-888888888888', 'dddddddd-dddd-dddd-dddd-dddddddddddd', '33333333-3333-3333-3333-333333333333', 'Thanks for setting this up'),
            ('77777777-7777-7777-7777-777777777777', 'ffffffff-ffff-ffff-ffff-ffffffffffff', '44444444-4444-4444-4444-444444444444', 'RLS is really powerful!'),
            ('66666666-6666-6666-6666-666666666666', 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', '11111111-1111-1111-1111-111111111111', 'Welcome Charlie!')
            ON CONFLICT (id) DO NOTHING;
        """)
        print("✓ Created 4 sample comments")

        # Create indexes for better RLS performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_channels_owner_id ON channels(owner_id);
            CREATE INDEX IF NOT EXISTS idx_channels_is_public ON channels(is_public);
            CREATE INDEX IF NOT EXISTS idx_channel_moderators_channel_user ON channel_moderators(channel_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_channel_moderators_user ON channel_moderators(user_id);
            CREATE INDEX IF NOT EXISTS idx_posts_channel_id ON posts(channel_id);
            CREATE INDEX IF NOT EXISTS idx_posts_author_id ON posts(author_id);
            CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at);
            CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
            CREATE INDEX IF NOT EXISTS idx_comments_author_id ON comments(author_id);
            CREATE INDEX IF NOT EXISTS idx_comments_created_at ON comments(created_at);
            CREATE INDEX IF NOT EXISTS idx_users_is_public ON users(is_public);
        """)
        print("✓ Created performance indexes for RLS")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error setting up environment: {e}")
        sys.exit(1)

if __name__ == "__main__":
    setup_rls_environment()
