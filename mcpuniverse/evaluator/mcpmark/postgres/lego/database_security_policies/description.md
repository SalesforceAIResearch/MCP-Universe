Implement a comprehensive database security system with Row-Level Security (RLS) policies and role-based access control for the LEGO database. The system must ensure theme-based data isolation and prevent unauthorized access across different LEGO themes.

## Your Tasks:

1. **Create database role and permissions** — Create a new database role called `theme_analyst` with the following permissions:
   * `SELECT` permissions on all reference tables: `lego_themes`, `lego_colors`, `lego_parts`, `lego_part_categories`
   * `SELECT` permissions on main data tables: `lego_sets`, `lego_inventories`, `lego_inventory_parts`
   * No `INSERT`, `UPDATE`, or `DELETE` permissions on any tables

2. **Enable Row-Level Security** — Enable RLS on the following tables:
   * `lego_sets`
   * `lego_inventories` 
   * `lego_inventory_parts`

3. **Create RLS policies** — Implement theme-based data isolation policies:
   
   **Policy 1: `theme_sets_policy` on `lego_sets`**
   * Allows access only to sets where `theme_id = 18` (Star Wars theme)
   * Policy should use a function that checks the current user's theme assignment
   
   **Policy 2: `theme_inventories_policy` on `lego_inventories`**
   * Allows access only to inventories for sets with `theme_id = 18`
   * Must join with `lego_sets` table to check theme_id
   
   **Policy 3: `theme_inventory_parts_policy` on `lego_inventory_parts`**
   * Allows access only to inventory parts for sets with `theme_id = 18`
   * Must join through `lego_inventories` and `lego_sets` to check theme_id

4. **Create theme assignment function** — Create a function `get_user_theme_id()` that:
   * Returns `18` for the `theme_analyst` role (Star Wars theme)
   * Can be extended to support other themes in the future
   * Uses `current_user` to determine the appropriate theme_id

5. **Test the security implementation** — Execute verification queries that demonstrate:
   * Star Wars theme (theme_id=18) returns exactly 2 sets: '65081-1' and 'K8008-1'
   * Technic theme (theme_id=1) returns 0 sets when accessed by theme_analyst role
   * Cross-theme data access is properly blocked
   * Reference tables are accessible for all data

6. **Create comprehensive security audit** — Generate a detailed report including:
   * Complete SQL statements for role creation and policy implementation
   * Expected query results for each theme
   * Verification queries to confirm proper data isolation
   * Documentation of the security model and access patterns

## Security Requirements:

- The `theme_analyst` role must only see data related to Star Wars theme (theme_id=18)
- All other themes must be completely hidden from this role
- Reference tables (themes, colors, parts, part_categories) must be fully accessible
- The system must prevent any cross-theme data leakage
- RLS policies must be active and enforced for all data access

## Expected Results:

When the `theme_analyst` role queries the database:
- `lego_sets` should return only 2 Star Wars sets
- `lego_inventories` should return only inventories for those 2 sets  
- `lego_inventory_parts` should return only parts for those 2 sets
- All reference tables should return complete data
- Queries for other themes should return empty results
