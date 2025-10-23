Implement a data consistency enforcement system for the LEGO database. The system must ensure that the reported part count in the `lego_sets` table matches the actual sum of non-spare parts in the latest inventory version. This involves a three-step process: identifying existing inconsistencies, fixing them, and creating a trigger-based constraint system to prevent future issues.

### Consistency Rule
For any given `set_num`, the following invariant must be maintained:
`lego_sets.num_parts = SUM(quantity)` FROM `lego_inventory_parts` WHERE `inventory_id` IN (latest inventory for that set) AND `is_spare` = false

**Important**: If a set has no inventory records, the consistency check should be skipped.

# Your Tasks:

## Task 1: Identify Data Inconsistencies

### Objective
Write a single `SELECT` query to find all sets where the stored `num_parts` does not match the actual calculated number of parts from the latest inventory.

1.  **Find the Latest Inventory**: For each `set_num`, find its latest inventory id by getting the `MAX(version)` from the `lego_inventories` table.
2.  **Calculate Actual Part Count**: For these latest inventories, join with `lego_inventory_parts` and calculate the `SUM(quantity)`, but only for parts where `is_spare` is false.
3.  **Compare and Filter**: Join this calculated result back to the `lego_sets` table and return the rows where `lego_sets.num_parts` is different from your calculated sum.

## Task 2: Fix Existing Inconsistencies

### Objective
Correct all mismatched `num_parts` values using a clear, multi-step process with a temporary table. This approach is designed to be robust against all edge cases.

#### Step 1: Create a Temporary Table
Create a temporary table (e.g., `correct_counts`) with two columns: `set_num` (text) and `actual_parts` (integer).

#### Step 2: Populate the Temporary Table
This is the most critical step. Write an `INSERT` statement that calculates the correct part count for every single set listed in the `lego_sets` table.

-   The query must start by selecting from `public.lego_sets`.
-   It must then `LEFT JOIN` to a subquery that contains the part-counting logic (finding the latest inventory version and summing the non-spare parts).
-   Use `COALESCE` on the final result from the subquery to ensure that any set without parts or without an inventory record gets a value of `0`, not `NULL`.

#### Step 3: Update from the Temporary Table

Write a final, simple `UPDATE` statement that joins the `lego_sets` table with your temporary table on `set_num` and sets `num_parts` to the `actual_parts` value.

## Task 3: Create Constraint Enforcement System

### Objective

Implement a deferrable constraint trigger system to enforce the consistency rule automatically for all future `INSERT` and `UPDATE` operations.

### Part A: Create the Trigger Function

Create a single PL/pgSQL function, preferably named `check_set_parts_consistency()`, that performs the core validation.

**Function Requirements**:

  - Returns `trigger`.
  - Accepts no arguments.
  - Contains the core validation logic:
      - **Identify the `set_num` to check**. This is the most critical part. The `set_num` must be retrieved based on which table fired the trigger (`TG_TABLE_NAME`):
          - If `lego_sets` or `lego_inventories`: get the `set_num` directly from `NEW.set_num`.
          - If `lego_inventory_parts`: you must first query `lego_inventories` using `NEW.inventory_id` to find the corresponding `set_num`.
      - **Perform the check**. For the identified `set_num`, execute the same core logic from Task 1 to get the `actual_parts` count and the `stored_num_parts` from the `lego_sets` table.
      - **Raise an exception on failure**. If `actual_parts` does not equal `stored_num_parts`, the function must raise an exception to block the transaction (e.g., `RAISE EXCEPTION 'Inconsistent part count for set %', relevant_set_num;`).
      - **Return `NEW` on success**. If the check passes or is skipped, the function should `RETURN NEW`.

### Part B: Create the Constraint Triggers

Create three separate `CONSTRAINT TRIGGER` statements that attach the function from Part A to the following tables:

  - `public.lego_sets`
  - `public.lego_inventories`
  - `public.lego_inventory_parts`

**Crucial Trigger Requirements**:

  - Each trigger must fire `AFTER INSERT OR UPDATE`.
  - Each trigger **MUST** be `DEFERRABLE` and `INITIALLY IMMEDIATE`. This is non-negotiable for the verification to pass.
  - Each trigger must execute the function `FOR EACH ROW`.