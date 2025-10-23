Fix the customer analysis query that is producing incorrect results.

## Background

The data analytics team attempted to create a customer behavior analysis query to identify active customers and analyze their spending patterns and preferences. The requirements are:
- Only count rentals that have associated payment records (paid rentals)
- Only include customers with at least 15 paid rentals
- Only include customers with valid email addresses

However, they're getting incorrect results - the query is over-counting rentals and calculating wrong spending amounts. 

Your task is to fix this query to produce accurate results.

## The Problematic Query

Here's the buggy query that needs to be fixed:

```sql
WITH customer_basic_stats AS (
    SELECT 
        c.customer_id,
        c.first_name || ' ' || c.last_name as customer_name,
        ci.city as customer_city,
        co.country as customer_country,
        COUNT(r.rental_id) as total_rentals,
        COUNT(DISTINCT i.film_id) as unique_films,
        SUM(p.amount) as total_spent,
        AVG(EXTRACT(days FROM (r.return_date - r.rental_date))) as avg_rental_duration
    FROM customer c
    JOIN address a ON c.address_id = a.address_id
    JOIN city ci ON a.city_id = ci.city_id
    JOIN country co ON ci.country_id = co.country_id
    JOIN rental r ON c.customer_id = r.customer_id
    JOIN inventory i ON r.inventory_id = i.inventory_id
    JOIN payment p ON r.rental_id = p.rental_id
    WHERE c.email IS NOT NULL
    GROUP BY c.customer_id, c.first_name, c.last_name, ci.city, co.country
    HAVING COUNT(r.rental_id) >= 15
),
customer_categories AS (
    SELECT 
        c.customer_id,
        cat.name as category_name,
        COUNT(*) as category_count,
        ROW_NUMBER() OVER (PARTITION BY c.customer_id ORDER BY COUNT(*) DESC, cat.name ASC) as rn
    FROM customer c
    JOIN rental r ON c.customer_id = r.customer_id
    JOIN inventory i ON r.inventory_id = i.inventory_id
    JOIN film f ON i.film_id = f.film_id
    JOIN film_category fc ON f.film_id = fc.film_id
    JOIN category cat ON fc.category_id = cat.category_id
    JOIN payment p ON r.rental_id = p.rental_id
    WHERE c.email IS NOT NULL
    GROUP BY c.customer_id, cat.name
),
customer_actors AS (
    SELECT 
        c.customer_id,
        a.first_name || ' ' || a.last_name as actor_name,
        COUNT(*) as actor_count,
        ROW_NUMBER() OVER (PARTITION BY c.customer_id ORDER BY COUNT(*) DESC, (a.first_name || ' ' || a.last_name) ASC) as rn
    FROM customer c
    JOIN rental r ON c.customer_id = r.customer_id
    JOIN inventory i ON r.inventory_id = i.inventory_id
    JOIN film f ON i.film_id = f.film_id
    JOIN film_actor fa ON f.film_id = fa.film_id
    JOIN actor a ON fa.actor_id = a.actor_id
    JOIN payment p ON r.rental_id = p.rental_id
    WHERE c.email IS NOT NULL
    GROUP BY c.customer_id, a.first_name, a.last_name
),
regional_popular_films AS (
    SELECT 
        co.country,
        f.title,
        COUNT(*) as rental_count,
        ROW_NUMBER() OVER (PARTITION BY co.country ORDER BY COUNT(*) DESC, f.title ASC) as rn
    FROM rental r
    JOIN inventory i ON r.inventory_id = i.inventory_id
    JOIN film f ON i.film_id = f.film_id
    JOIN customer c ON r.customer_id = c.customer_id
    JOIN address a ON c.address_id = a.address_id
    JOIN city ci ON a.city_id = ci.city_id
    JOIN country co ON ci.country_id = co.country_id
    JOIN payment p ON r.rental_id = p.rental_id
    WHERE c.email IS NOT NULL
    GROUP BY co.country, f.title
)
SELECT 
    cbs.customer_id,
    cbs.customer_name,
    cbs.customer_city,
    cbs.customer_country,
    cbs.total_rentals,
    cbs.unique_films,
    cbs.total_spent,
    cc.category_name as favorite_category,
    ca.actor_name as favorite_actor,
    cbs.avg_rental_duration,
    CASE 
        WHEN cbs.total_spent >= 150 THEN 'Premium'
        WHEN cbs.total_spent >= 75 THEN 'Standard'
        ELSE 'Basic'
    END as customer_tier,
    rpf.title as most_popular_film_in_region,
    rpf.rental_count as regional_film_rental_count
FROM customer_basic_stats cbs
LEFT JOIN customer_categories cc ON cbs.customer_id = cc.customer_id AND cc.rn = 1
LEFT JOIN customer_actors ca ON cbs.customer_id = ca.customer_id AND ca.rn = 1
LEFT JOIN regional_popular_films rpf ON cbs.customer_country = rpf.country AND rpf.rn = 1
ORDER BY cbs.total_spent DESC, cbs.total_rentals DESC, cbs.customer_name ASC;
```

## Known Issues

When comparing the problematic query results with the expected correct values, the following discrepancies are observed:

1. **Rental count discrepancies**: Many customers show higher `total_rentals` counts than expected

2. **Spending amount errors**: The `total_spent` values don't match the correct calculations 

3. **Incorrect favorite categories and actors**: Many customers show wrong favorite categories and actors compared to the expected results

4. **Time calculation inconsistencies**: The `avg_rental_duration` values differ significantly from the correct calculations
    - Example: Customer ID 1 shows 3.90 days instead of the expected 4.27 days
    - Example: Customer ID 2 shows 5.23 days instead of the expected 5.69 days

## Your Task

Debug and fix the query to produce accurate results. Then create a table with your corrected results.

1. **Fix the query** to ensure:
   - Accurate customer spending and rental counts
   - Correct favorite categories and actors
   - Proper regional popular films

2. **Create a table** called `customer_analysis_fixed` in the `public` schema with your corrected query results. The table should have the same columns as the original query output.

**Important**: The business logic and output columns should remain the same - only fix the data accuracy issues.