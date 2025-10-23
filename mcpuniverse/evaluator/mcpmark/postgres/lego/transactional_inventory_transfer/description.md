Create a PostgreSQL function to handle inventory part transfers between LEGO sets with enhanced validation and audit capabilities. The LEGO warehouse management system needs to support transferring parts while maintaining data integrity and tracking transfer history.

## Your Tasks:

1. **Create the transfer function** — Implement a PostgreSQL function named `transfer_parts` with the following signature:
   ```sql
   CREATE OR REPLACE FUNCTION transfer_parts(
       source_inventory_id INTEGER,
       target_inventory_id INTEGER,
       part_to_transfer_num VARCHAR,
       color_to_transfer_id INTEGER,
       quantity_to_transfer INTEGER,
       transfer_reason VARCHAR DEFAULT 'manual_transfer'
   ) RETURNS TEXT
   ```

2. **Create audit logging table** — Create a new table to track transfer history:
   ```sql
   CREATE TABLE inventory_transfer_log (
       log_id SERIAL PRIMARY KEY,
       transfer_timestamp TIMESTAMP DEFAULT NOW(),
       source_inventory_id INTEGER NOT NULL,
       target_inventory_id INTEGER NOT NULL,
       part_num VARCHAR NOT NULL,
       color_id INTEGER NOT NULL,
       quantity_transferred INTEGER NOT NULL,
       transfer_reason VARCHAR NOT NULL,
       transfer_status VARCHAR NOT NULL CHECK (transfer_status IN ('success', 'failed')),
       error_message TEXT
   );
   ```

3. **Implement enhanced validation** — The function must perform these validations:
   
   **Validation A: Basic Checks**
   - Verify both inventory IDs exist in `lego_inventories` table
   - Verify part exists in `lego_parts` table
   - Verify color exists in `lego_colors` table
   - Check source has sufficient quantity (including spare parts)
   - Prevent self-transfers (source and target cannot be the same)

   **Validation B: Business Rules**
   - Maximum transfer quantity is 500 parts per operation
   - Minimum transfer quantity is 1 part
   - Source and target must be different inventories

4. **Implement transactional logic** — The function must perform these operations within a single transaction:
   
   **Step A: Pre-validation**
   - Lock both inventory records using `SELECT ... FOR UPDATE`
   - Perform all validation checks
   - Calculate transfer feasibility

   **Step B: Source Inventory Update**
   - Decrease quantity in source inventory
   - If quantity becomes zero, delete the row
   - Handle spare parts appropriately (maintain `is_spare` flag)

   **Step C: Target Inventory Update**
   - Check if part exists in target inventory
   - If exists: increase quantity
   - If not exists: insert new record
   - Handle spare parts appropriately

   **Step D: Audit Logging**
   - Log successful transfers with details
   - Log failed transfers with error messages
   - Include transfer reason and status

5. **Error handling requirements**:
   - Use `RAISE EXCEPTION` with descriptive error messages
   - Handle all validation failures gracefully
   - Ensure complete rollback on any failure
   - Log all attempts (successful and failed)

6. **Return value**:
   - Return success message: `'Successfully transferred {quantity} parts ({part_num}, color_id: {color_id}) from inventory {source_id} to inventory {target_id}. Reason: {reason}'`
   - Include transfer details and reason in the message

## Function Requirements:

- **Transaction Safety**: All operations wrapped in transaction block
- **Data Integrity**: No partial updates possible
- **Audit Trail**: Complete logging of all transfer attempts
- **Validation**: Comprehensive input and business rule validation
- **Error Recovery**: Failed transfers leave database unchanged
- **Performance**: Use appropriate locking to prevent race conditions

## Example Usage:

```sql
-- Basic transfer with reason
SELECT transfer_parts(14469, 14686, '3024', 15, 100, 'inventory_adjustment');

-- Transfer to new inventory (should create new record)
SELECT transfer_parts(11124, 14686, '3001', 4, 50, 'part_redistribution');

-- This should fail due to insufficient quantity
SELECT transfer_parts(14469, 14686, '3024', 15, 2000, 'large_transfer');

-- This should fail due to self-transfer
SELECT transfer_parts(14469, 14469, '3024', 15, 10, 'self_transfer');
```

## Verification Criteria:

- Function handles all validation rules correctly
- Audit logging captures all transfer attempts
- Failed transfers are properly logged with error details
- Self-transfers are prevented
- Quantity limits are enforced
- Database state remains consistent after failures