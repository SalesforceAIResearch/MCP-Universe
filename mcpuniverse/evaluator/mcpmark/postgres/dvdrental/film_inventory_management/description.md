Manage film inventory operations in the DVD rental database.

## Background

You are the database administrator for the DVD rental store. The store manager has requested several database operations to manage the film inventory. You need to perform multiple operations including adding new films, updating inventory, querying available films, and cleaning up old records.

## Your Task

Complete the following database operations in sequence:

### 1. Add New Films
Add these two new films to the database:
- **Film 1**: Title "Data Science Adventures", Description "A thrilling journey through machine learning algorithms", Release Year 2024, Language ID 1, Rental Duration 5 days, Rental Rate $3.99, Length 120 minutes, Replacement Cost $15.99, Rating 'PG-13'
- **Film 2**: Title "Cloud Computing Chronicles", Description "Exploring the world of distributed systems", Release Year 2024, Language ID 1, Rental Duration 7 days, Rental Rate $4.99, Length 135 minutes, Replacement Cost $18.99, Rating 'PG'

### 2. Add Inventory Records
For each new film, add 3 inventory records for store_id = 1 and 2 inventory records for store_id = 2.

### 3. Update Film Information
Update the rental_rate of all films with rating 'PG-13' to increase by 10% (multiply by 1.1).

### 4. Create Available Films Table
Create a table called `available_films` with the following structure:
- `film_id` (INTEGER, PRIMARY KEY)
- `title` (VARCHAR(255), NOT NULL)
- `rental_rate` (NUMERIC(4,2), NOT NULL)
- `length` (SMALLINT)

Populate this table with films that meet these criteria:
- Have rental_rate between $3.00 and $5.00
- Have length greater than 100 minutes  
- Are available in store_id = 1 (have at least 1 inventory record)


### 5. Clean Up Inventory
Delete inventory records for films that meet ALL of the following criteria:
- Have a replacement_cost greater than $25.00
- AND have rental_rate less than $1.00
- AND have no rental history (no records in the rental table)


### 6. Create Summary Report Table
Create a table called `film_inventory_summary` with the following structure:
- `title` (VARCHAR(255), NOT NULL)
- `rental_rate` (NUMERIC(4,2), NOT NULL)
- `total_inventory` (INTEGER, NOT NULL)
- `store1_count` (INTEGER, NOT NULL)
- `store2_count` (INTEGER, NOT NULL)

Populate this table with a summary query that shows:
- Film title
- Current rental rate (after any updates from step 3)
- Total count of inventory records across all stores
- Count of inventory records in store_id = 1
- Count of inventory records in store_id = 2

Requirements for the summary report:
- Include only films that currently have at least one inventory record  
- Insert the results sorted by inventory count from highest to lowest, and then alphabetically by film title
- Ensure all counts reflect the state after completing the previous operations

## Requirements

- Complete all operations in the specified sequence
- Ensure data integrity throughout all operations
- Verify that your operations affect the expected number of records
- Handle any constraint violations appropriately