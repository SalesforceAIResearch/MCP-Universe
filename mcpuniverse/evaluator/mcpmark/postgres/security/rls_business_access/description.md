Implement Row Level Security (RLS) policies for a social media platform with Users, Posts, Comments, and Channels.

## Your Mission:

Build RLS policies for a social platform where users create posts and comments in channels. Implement proper access control so users can manage their own content, while channel moderators can moderate content in their channels.

## RLS Requirements:

### 1. Users Table Access Rules:
- **SELECT**: Users can read all public user profiles (username, created_at)
- **UPDATE**: Users can only modify their own profile
- **DELETE**: Users can only delete their own account

### 2. Channels Table Access Rules:
- **SELECT**: Everyone can read public channel information
- **INSERT**: Any authenticated user can create a channel (becomes owner)
- **UPDATE**: Only channel owners can modify channel details
- **DELETE**: Only channel owners can delete channels

### 3. Posts Table Access Rules:
- **SELECT**: Users can read all posts in channels they have access to
- **INSERT**: Authenticated users can create posts in any channel
- **UPDATE**: Post authors OR channel moderators OR channel owners can edit posts
- **DELETE**: Post authors OR channel moderators OR channel owners can delete posts

### 4. Comments Table Access Rules:
- **SELECT**: Users can read comments on posts they can access
- **INSERT**: Authenticated users can comment on posts they can see
- **UPDATE**: Comment authors OR post authors OR channel moderators OR channel owners can edit comments
- **DELETE**: Comment authors OR post authors OR channel moderators OR channel owners can delete comments

### 5. Channel Moderators Table Access Rules:
- **SELECT**: Users can see moderator lists for channels
- **INSERT**: Only channel owners can add moderators
- **DELETE**: Channel owners can remove moderators; moderators can remove themselves

## Session Context:

Use `current_setting('app.current_user_id')` to get the current user ID from session context.

## Schema Requirements:

- **Use only the `public` schema** for all tables, functions, and policies
- All helper functions should be created in the `public` schema
- Do not create additional schemas

## Expected Deliverables:

1. **Enable RLS** on all five tables
2. **Create policies** for SELECT, INSERT, UPDATE, DELETE operations on each table
3. **Helper functions** to check permissions efficiently:
   - `is_channel_owner(channel_id, user_id)`
   - `is_channel_moderator(channel_id, user_id)`
   - `can_moderate_channel(channel_id, user_id)`
4. **Proper indexing** to ensure RLS policies perform well

## Test Scenarios:

Your RLS implementation will be verified with:

- **Content ownership**: Users can only edit their own posts/comments
- **Moderation hierarchy**: Moderators can moderate content in their channels
- **Channel isolation**: Users only see content from accessible channels
- **Permission escalation**: Owners have full control over their channels
- **Cross-table access**: Comment policies respect post and channel permissions

## Success Criteria:

- Users can manage their own content (posts, comments)
- Channel owners have full control over their channels
- Moderators can moderate content in their assigned channels
- No unauthorized access to other users' private data
- Policies are efficient and don't create performance bottlenecks
- All operations (SELECT, INSERT, UPDATE, DELETE) are properly secured
