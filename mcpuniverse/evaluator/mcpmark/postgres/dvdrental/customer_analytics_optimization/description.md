Optimize slow customer analytics query in the DVD rental database.

## Background

The business intelligence team is running customer analytics reports, but one of their critical queries has become extremely slow. The query that used to run in milliseconds is now taking over a second to complete, causing timeout issues in their reporting dashboard.

## Your Task

Analyze and optimize the performance of this customer analytics query:

```sql
SELECT 
    c.customer_id,
    c.first_name,
    c.last_name,
    c.email,
    COUNT(DISTINCT p.payment_id) as total_payments,
    SUM(p.amount) as total_spent,
    AVG(p.amount) as avg_payment,
    COUNT(DISTINCT EXTRACT(month FROM p.payment_date)) as active_months,
    MAX(p.payment_date) as last_payment,
    MIN(p.payment_date) as first_payment,
    (SELECT COUNT(*) FROM payment p2 WHERE p2.customer_id = c.customer_id AND p2.amount > 5.0) as high_value_payments,
    (SELECT SUM(amount) FROM payment p3 WHERE p3.customer_id = c.customer_id AND p3.payment_date >= '2007-03-01') as recent_spending
FROM customer c
JOIN payment p ON c.customer_id = p.customer_id
WHERE c.active = 1
GROUP BY c.customer_id, c.first_name, c.last_name, c.email
HAVING COUNT(p.payment_id) >= 10
ORDER BY total_spent DESC, total_payments DESC;
```

The query is currently taking over 1000ms to execute and has a very high cost in the execution plan. The team needs this optimized urgently as it's blocking their daily reporting processes.

## Requirements

- Use `EXPLAIN ANALYZE` to identify performance bottlenecks
- Implement appropriate database optimizations  
- Ensure queries return accurate results after optimization
- Document your optimization approach and performance improvements