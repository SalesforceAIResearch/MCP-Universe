#!/usr/bin/env python3

"""Verification module for RLS business access task."""
# pylint: disable=too-many-branches,too-many-locals,too-many-statements,duplicate-code
import os
import sys

import psycopg2  # type: ignore
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def verify() -> tuple[bool, str]:
    """
    Verify that Row Level Security policies have been properly implemented
    for the social media platform with Users, Posts, Comments, and Channels.
    """

    # Database connection parameters from environment
    admin_db_params = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'user': os.getenv('POSTGRES_USERNAME', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'password'),
        'database': os.getenv('POSTGRES_DATABASE', 'postgres')
    }

    # Test user parameters (non-superuser for proper RLS testing)
    test_db_params = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'user': 'test_user',
        'password': 'testpass',
        'database': os.getenv('POSTGRES_DATABASE', 'postgres')
    }

    try:
        # First connect as admin to ensure test user exists
        admin_conn = psycopg2.connect(**admin_db_params)
        admin_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        admin_cur = admin_conn.cursor()

        # Create test user if it doesn't exist
        try:
            admin_cur.execute("CREATE ROLE test_user LOGIN PASSWORD 'testpass';")
        except psycopg2.Error:
            pass  # User already exists

        # Grant necessary permissions to test user on the current database
        admin_cur.execute("SELECT current_database();")
        current_db_name = admin_cur.fetchone()[0]

        admin_cur.execute(
            f"GRANT CONNECT ON DATABASE \"{current_db_name}\" TO test_user;"
        )
        admin_cur.execute("GRANT USAGE ON SCHEMA public TO test_user;")
        admin_cur.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
            "IN SCHEMA public TO test_user;"
        )
        admin_cur.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO test_user;")
        admin_cur.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO test_user;")

        admin_cur.close()
        admin_conn.close()

        # Update test_db_params with the correct database name
        test_db_params['database'] = current_db_name

        # Now connect as test user for RLS verification
        conn = psycopg2.connect(**test_db_params)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        print("Verifying...")

        test_results = []

        # Test 1: Check if RLS is enabled on all tables
        print("\n1. Checking RLS enablement...")
        expected_tables = ['users', 'channels', 'channel_moderators', 'posts', 'comments']

        for table in expected_tables:
            cur.execute("""
                SELECT relrowsecurity
                FROM pg_class
                WHERE relname = %s AND relkind = 'r'
            """, (table,))
            result = cur.fetchone()

            if result and result[0]:
                test_results.append(f"✓ RLS enabled on {table}")
            else:
                test_results.append(f"✗ RLS NOT enabled on {table}")

        # Test 2: Users can only update their own profile
        print("\n2. Testing user profile access control...")

        # Alice tries to update her own profile (should work)
        try:
            # Alice
            cur.execute(
                "SET app.current_user_id = '11111111-1111-1111-1111-111111111111';"
            )
            cur.execute("""
                UPDATE users
                SET email = 'alice.updated@example.com'
                WHERE id = '11111111-1111-1111-1111-111111111111'
            """)
            test_results.append("✓ Users can update their own profile")
        except psycopg2.Error as e:
            test_results.append(f"✗ User cannot update own profile: {e}")

        # Alice tries to update Bob's profile (should fail)
        try:
            # Alice
            cur.execute(
                "SET app.current_user_id = '11111111-1111-1111-1111-111111111111';"
            )
            cur.execute("""
                UPDATE users
                SET email = 'bob.hacked@example.com'
                WHERE id = '22222222-2222-2222-2222-222222222222'
            """)
            # Check if the update actually affected any rows (RLS blocks by affecting 0 rows)
            if cur.rowcount == 0:
                test_results.append("✓ Users blocked from updating other users' profiles")
            else:
                test_results.append(
                    "✗ User was able to update another user's profile "
                    "(should be blocked)"
                )
        except psycopg2.Error:
            test_results.append("✓ Users blocked from updating other users' profiles")

        # Test 3: Channel ownership controls
        print("\n3. Testing channel ownership controls...")

        # Alice (owner of general channel) tries to update her channel
        try:
            # Alice
            cur.execute(
                "SET app.current_user_id = '11111111-1111-1111-1111-111111111111';"
            )
            cur.execute("""
                UPDATE channels
                SET description = 'Updated by Alice'
                WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            """)
            test_results.append("✓ Channel owners can update their channels")
        except psycopg2.Error as e:
            test_results.append(f"✗ Channel owner cannot update channel: {e}")

        # Charlie tries to update Alice's channel (should fail)
        try:
            # Charlie
            cur.execute(
                "SET app.current_user_id = '33333333-3333-3333-3333-333333333333';"
            )
            cur.execute("""
                UPDATE channels
                SET description = 'Hacked by Charlie'
                WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            """)
            # Check if the update actually affected any rows (RLS blocks by affecting 0 rows)
            if cur.rowcount == 0:
                test_results.append("✓ Non-owners blocked from updating channels")
            else:
                test_results.append(
                    "✗ Non-owner was able to update channel "
                    "(should be blocked)"
                )
        except psycopg2.Error:
            test_results.append("✓ Non-owners blocked from updating channels")

        # Test 4: Post authorship and moderation controls
        print("\n4. Testing post access controls...")

        # Alice (author) tries to update her own post
        try:
            # Alice
            cur.execute(
                "SET app.current_user_id = '11111111-1111-1111-1111-111111111111';"
            )
            cur.execute("""
                UPDATE posts
                SET title = 'Updated by Alice'
                WHERE id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
            """)
            test_results.append("✓ Post authors can update their posts")
        except psycopg2.Error as e:
            test_results.append(f"✗ Post author cannot update post: {e}")

        # Bob (moderator of general) tries to update Alice's post (should work)
        try:
            # Bob (moderator)
            cur.execute(
                "SET app.current_user_id = '22222222-2222-2222-2222-222222222222';"
            )
            cur.execute("""
                UPDATE posts
                SET content = 'Moderated by Bob'
                WHERE id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
            """)
            test_results.append("✓ Channel moderators can update posts in their channels")
        except psycopg2.Error as e:
            test_results.append(f"✗ Channel moderator cannot update post: {e}")

        # Eve tries to update Alice's post (should fail - not author, owner, or moderator)
        try:
            cur.execute("SET app.current_user_id = '55555555-5555-5555-5555-555555555555';")  # Eve
            cur.execute("""
                UPDATE posts
                SET content = 'Hacked by Eve'
                WHERE id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
            """)
            # Check if the update actually affected any rows (RLS blocks by affecting 0 rows)
            if cur.rowcount == 0:
                test_results.append("✓ Unauthorized users blocked from updating posts")
            else:
                test_results.append(
                    "✗ Unauthorized user was able to update post "
                    "(should be blocked)"
                )
        except psycopg2.Error:
            test_results.append("✓ Unauthorized users blocked from updating posts")

        # Test 5: Comment access controls
        print("\n5. Testing comment access controls...")

        # Bob (comment author) tries to update his own comment
        try:
            # Bob
            cur.execute(
                "SET app.current_user_id = '22222222-2222-2222-2222-222222222222';"
            )
            cur.execute("""
                UPDATE comments
                SET content = 'Updated by Bob himself'
                WHERE id = '99999999-9999-9999-9999-999999999999'
            """)
            test_results.append("✓ Comment authors can update their comments")
        except psycopg2.Error as e:
            test_results.append(f"✗ Comment author cannot update comment: {e}")

        # Alice (post author) tries to update Bob's comment on her post
        # (should work)
        try:
            # Alice (post author)
            cur.execute(
                "SET app.current_user_id = '11111111-1111-1111-1111-111111111111';"
            )
            cur.execute("""
                UPDATE comments
                SET content = 'Moderated by post author Alice'
                WHERE id = '99999999-9999-9999-9999-999999999999'
            """)
            test_results.append("✓ Post authors can moderate comments on their posts")
        except psycopg2.Error as e:
            test_results.append(f"✗ Post author cannot moderate comment: {e}")

        # Test 6: Channel moderator assignment controls
        print("\n6. Testing moderator assignment controls...")

        # Alice (channel owner) tries to add a moderator
        try:
            # Alice (owner of general)
            cur.execute(
                "SET app.current_user_id = '11111111-1111-1111-1111-111111111111';"
            )
            cur.execute("""
                INSERT INTO channel_moderators (channel_id, user_id)
                VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '33333333-3333-3333-3333-333333333333')
            """)
            test_results.append("✓ Channel owners can add moderators")
        except psycopg2.Error as e:
            test_results.append(f"✗ Channel owner cannot add moderator: {e}")

        # Charlie tries to add himself as moderator to Bob's channel
        # (should fail)
        try:
            # Charlie
            cur.execute(
                "SET app.current_user_id = '33333333-3333-3333-3333-333333333333';"
            )
            cur.execute("""
                INSERT INTO channel_moderators (channel_id, user_id)
                VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '33333333-3333-3333-3333-333333333333')
            """)
            # Check if the insert actually affected any rows (RLS blocks by affecting 0 rows)
            if cur.rowcount == 0:
                test_results.append("✓ Non-owners blocked from adding moderators")
            else:
                test_results.append(
                    "✗ Non-owner was able to add moderator "
                    "(should be blocked)"
                )
        except psycopg2.Error:
            test_results.append("✓ Non-owners blocked from adding moderators")

        # Test 7: Content visibility based on user context
        print("\n7. Testing content visibility...")

        # Count posts visible to Alice
        cur.execute("SET app.current_user_id = '11111111-1111-1111-1111-111111111111';")  # Alice
        cur.execute("SELECT COUNT(*) FROM posts;")
        alice_posts = cur.fetchone()[0]

        # Count posts visible to Eve
        cur.execute("SET app.current_user_id = '55555555-5555-5555-5555-555555555555';")  # Eve
        cur.execute("SELECT COUNT(*) FROM posts;")
        eve_posts = cur.fetchone()[0]

        # Alice should see posts in channels she has access to
        if alice_posts >= 2 and eve_posts >= 1:
            test_results.append(
                "✓ Content visibility varies correctly based on user context"
            )
        else:
            test_results.append(
                f"✗ Content visibility issue: Alice sees {alice_posts}, "
                f"Eve sees {eve_posts}"
            )

        # Test 8: Anonymous user access
        print("\n8. Testing anonymous user restrictions...")

        try:
            cur.execute("SET app.current_user_id = '';")  # Anonymous user
            cur.execute("SELECT COUNT(*) FROM users;")
            anon_users = cur.fetchone()[0]

            # Anonymous users should be able to see public user profiles per requirements
            # Count public users that should be visible
            cur.execute("SELECT COUNT(*) FROM users WHERE is_public = true;")
            public_users = cur.fetchone()[0] if cur.rowcount > 0 else 0

            if anon_users == public_users and anon_users > 0:
                test_results.append(
                    f"✓ Anonymous users can see {anon_users} "
                    f"public user profiles (correct)"
                )
            elif anon_users == 0:
                test_results.append(
                    "✗ Anonymous users cannot see any users "
                    "(should see public profiles)"
                )
            else:
                test_results.append(
                    f"✗ Anonymous users can see {anon_users} users "
                    f"but expected {public_users} public users"
                )
        except psycopg2.Error:
            test_results.append("✓ Anonymous users properly restricted")

        # Print results
        print("\n" + "="*60)
        print("RLS VERIFICATION RESULTS - SOCIAL MEDIA PLATFORM")
        print("="*60)

        passed = sum(1 for result in test_results if result.startswith("✓"))
        failed = sum(1 for result in test_results if result.startswith("✗"))

        for result in test_results:
            print(result)

        print(f"\nSummary: {passed} passed, {failed} failed")

        cur.close()
        conn.close()

        if failed == 0:
            print("\nAll tests passed.")
            return True, ""
        print(f"\n{failed} test(s) failed.")
        error_details = [r for r in test_results if r.startswith("✗")]
        return False, f"{failed} test(s) failed: {'; '.join(error_details[:3])}"

    except (psycopg2.Error, ValueError, KeyError, TypeError) as e:
        print(f"Error during verification: {e}")
        return False, f"Error during verification: {e}"

def main():
    """Main verification function."""
    success, _error_msg = verify()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
