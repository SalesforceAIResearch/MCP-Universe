-- Ground Truth RLS Implementation

BEGIN;

-- ============================================================================
-- PERFORMANCE INDEXES FOR RLS
-- ============================================================================

-- Users table indexes
CREATE INDEX IF NOT EXISTS idx_users_is_public ON users(is_public);

-- Channels table indexes
CREATE INDEX IF NOT EXISTS idx_channels_owner_id ON channels(owner_id);
CREATE INDEX IF NOT EXISTS idx_channels_is_public ON channels(is_public);

-- Channel moderators table indexes
CREATE INDEX IF NOT EXISTS idx_channel_moderators_channel_user ON channel_moderators(channel_id, user_id);
CREATE INDEX IF NOT EXISTS idx_channel_moderators_user ON channel_moderators(user_id);

-- Posts table indexes
CREATE INDEX IF NOT EXISTS idx_posts_channel_id ON posts(channel_id);
CREATE INDEX IF NOT EXISTS idx_posts_author_id ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at);

-- Comments table indexes
CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_comments_author_id ON comments(author_id);
CREATE INDEX IF NOT EXISTS idx_comments_created_at ON comments(created_at);

-- ============================================================================
-- ENABLE ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_moderators ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE comments ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- USERS TABLE POLICIES
-- ============================================================================

-- Users SELECT: Can read public profiles OR own profile
DROP POLICY IF EXISTS users_select ON users;
CREATE POLICY users_select ON users
FOR SELECT
USING (
    is_public = true
    OR id = app_current_user_id()
);

-- Users UPDATE: Can only update own profile
DROP POLICY IF EXISTS users_update ON users;
CREATE POLICY users_update ON users
FOR UPDATE
USING (id = app_current_user_id())
WITH CHECK (id = app_current_user_id());

-- Users DELETE: Can only delete own account
DROP POLICY IF EXISTS users_delete ON users;
CREATE POLICY users_delete ON users
FOR DELETE
USING (id = app_current_user_id());

-- ============================================================================
-- CHANNELS TABLE POLICIES
-- ============================================================================

-- Channels SELECT: Can read public channels OR channels where user is owner/moderator
DROP POLICY IF EXISTS channels_select ON channels;
CREATE POLICY channels_select ON channels
FOR SELECT
USING (
    is_public = true
    OR owner_id = app_current_user_id()
    OR is_channel_moderator(id, app_current_user_id())
);

-- Channels INSERT: Authenticated users can create channels (become owner)
DROP POLICY IF EXISTS channels_insert ON channels;
CREATE POLICY channels_insert ON channels
FOR INSERT
WITH CHECK (owner_id = app_current_user_id());

-- Channels UPDATE: Only channel owners can modify
DROP POLICY IF EXISTS channels_update ON channels;
CREATE POLICY channels_update ON channels
FOR UPDATE
USING (owner_id = app_current_user_id())
WITH CHECK (owner_id = app_current_user_id());

-- Channels DELETE: Only channel owners can delete
DROP POLICY IF EXISTS channels_delete ON channels;
CREATE POLICY channels_delete ON channels
FOR DELETE
USING (owner_id = app_current_user_id());

-- ============================================================================
-- POSTS TABLE POLICIES
-- ============================================================================

-- Posts SELECT: Can read posts in accessible channels
DROP POLICY IF EXISTS posts_select ON posts;
CREATE POLICY posts_select ON posts
FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM channels c
        WHERE c.id = posts.channel_id
        AND (
            c.is_public = true
            OR c.owner_id = app_current_user_id()
            OR is_channel_moderator(c.id, app_current_user_id())
        )
    )
);

-- Posts INSERT: Authenticated users can create posts (must be author)
DROP POLICY IF EXISTS posts_insert ON posts;
CREATE POLICY posts_insert ON posts
FOR INSERT
WITH CHECK (
    author_id = app_current_user_id()
    AND EXISTS (
        SELECT 1 FROM channels c
        WHERE c.id = posts.channel_id
        AND (
            c.is_public = true
            OR c.owner_id = app_current_user_id()
            OR is_channel_moderator(c.id, app_current_user_id())
        )
    )
);

-- Posts UPDATE: Post authors OR channel moderators/owners can edit
DROP POLICY IF EXISTS posts_update ON posts;
CREATE POLICY posts_update ON posts
FOR UPDATE
USING (
    author_id = app_current_user_id()
    OR can_moderate_channel(channel_id, app_current_user_id())
)
WITH CHECK (
    author_id = app_current_user_id()
    OR can_moderate_channel(channel_id, app_current_user_id())
);

-- Posts DELETE: Post authors OR channel moderators/owners can delete
DROP POLICY IF EXISTS posts_delete ON posts;
CREATE POLICY posts_delete ON posts
FOR DELETE
USING (
    author_id = app_current_user_id()
    OR can_moderate_channel(channel_id, app_current_user_id())
);

-- ============================================================================
-- COMMENTS TABLE POLICIES
-- ============================================================================

-- Comments SELECT: Can read comments on accessible posts
DROP POLICY IF EXISTS comments_select ON comments;
CREATE POLICY comments_select ON comments
FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM posts p
        JOIN channels c ON c.id = p.channel_id
        WHERE p.id = comments.post_id
        AND (
            c.is_public = true
            OR c.owner_id = app_current_user_id()
            OR is_channel_moderator(c.id, app_current_user_id())
        )
    )
);

-- Comments INSERT: Authenticated users can comment on accessible posts
DROP POLICY IF EXISTS comments_insert ON comments;
CREATE POLICY comments_insert ON comments
FOR INSERT
WITH CHECK (
    author_id = app_current_user_id()
    AND EXISTS (
        SELECT 1 FROM posts p
        JOIN channels c ON c.id = p.channel_id
        WHERE p.id = comments.post_id
        AND (
            c.is_public = true
            OR c.owner_id = app_current_user_id()
            OR is_channel_moderator(c.id, app_current_user_id())
        )
    )
);

-- Comments UPDATE: Comment authors OR post authors OR channel moderators/owners can edit
DROP POLICY IF EXISTS comments_update ON comments;
CREATE POLICY comments_update ON comments
FOR UPDATE
USING (
    author_id = app_current_user_id()
    OR EXISTS (
        SELECT 1 FROM posts p
        WHERE p.id = comments.post_id
        AND (
            p.author_id = app_current_user_id()
            OR can_moderate_channel(p.channel_id, app_current_user_id())
        )
    )
)
WITH CHECK (
    author_id = app_current_user_id()
    OR EXISTS (
        SELECT 1 FROM posts p
        WHERE p.id = comments.post_id
        AND (
            p.author_id = app_current_user_id()
            OR can_moderate_channel(p.channel_id, app_current_user_id())
        )
    )
);

-- Comments DELETE: Comment authors OR post authors OR channel moderators/owners can delete
DROP POLICY IF EXISTS comments_delete ON comments;
CREATE POLICY comments_delete ON comments
FOR DELETE
USING (
    author_id = app_current_user_id()
    OR EXISTS (
        SELECT 1 FROM posts p
        WHERE p.id = comments.post_id
        AND (
            p.author_id = app_current_user_id()
            OR can_moderate_channel(p.channel_id, app_current_user_id())
        )
    )
);

-- ============================================================================
-- CHANNEL MODERATORS TABLE POLICIES
-- ============================================================================

-- Channel moderators SELECT: Visible to users who can access the channel
DROP POLICY IF EXISTS channel_moderators_select ON channel_moderators;
CREATE POLICY channel_moderators_select ON channel_moderators
FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM channels c
        WHERE c.id = channel_moderators.channel_id
        AND (
            c.is_public = true
            OR c.owner_id = app_current_user_id()
            OR is_channel_moderator(c.id, app_current_user_id())
        )
    )
);

-- Channel moderators INSERT: Only channel owners can add moderators
DROP POLICY IF EXISTS channel_moderators_insert ON channel_moderators;
CREATE POLICY channel_moderators_insert ON channel_moderators
FOR INSERT
WITH CHECK (is_channel_owner(channel_id, app_current_user_id()));

-- Channel moderators DELETE: Channel owners can remove any; moderators can remove themselves
DROP POLICY IF EXISTS channel_moderators_delete ON channel_moderators;
CREATE POLICY channel_moderators_delete ON channel_moderators
FOR DELETE
USING (
    is_channel_owner(channel_id, app_current_user_id())
    OR user_id = app_current_user_id()
);

-- ============================================================================
-- USAGE NOTES
-- ============================================================================

/*
Usage Instructions:
1. Set session context before queries:
   SET app.current_user_id = '<user-uuid>';

2. For anonymous users:
   SET app.current_user_id = '';

3. Test examples:
   -- Alice (owner of general channel)
   SET app.current_user_id = '11111111-1111-1111-1111-111111111111';

   -- Bob (moderator of general channel)
   SET app.current_user_id = '22222222-2222-2222-2222-222222222222';
*/

COMMIT;
