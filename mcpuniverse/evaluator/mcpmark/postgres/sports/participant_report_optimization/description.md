# Query Performance Optimization

## Background
You need to optimize a slow-running analytics query that generates performance reports. The query currently takes too long to execute and needs optimization.

## Requirements

### 1. Create Performance Report Table
Create a table called `participant_performance_report` with the following structure:
- report_id (serial primary key)
- participant_id (integer not null)
- event_count (integer)
- stat_count (integer)
- stat_type_count (integer)
- last_event_date (timestamp)
- created_at (timestamp default current_timestamp)

Add constraint: CHECK (participant_id > 0)

### 2. Execute and Optimize the Slow Query
The following query is currently running very slowly. Your task is to:
1. **Identify why the query is slow**
2. **Create appropriate indexes to optimize it** 
3. **Populate the report table with the query results**

```sql
SELECT 
    pe.participant_id,
    COUNT(pe.event_id) as event_count,
    (SELECT COUNT(*) FROM stats s WHERE s.stat_holder_id = pe.participant_id AND s.stat_holder_type = 'persons') as stat_count,
    (SELECT COUNT(DISTINCT s.stat_repository_type) FROM stats s WHERE s.stat_holder_id = pe.participant_id AND s.stat_holder_type = 'persons') as stat_type_count,
    (SELECT MAX(e.start_date_time) FROM events e JOIN participants_events pe2 ON e.id = pe2.event_id WHERE pe2.participant_id = pe.participant_id) as last_event_date
FROM participants_events pe 
WHERE pe.participant_id <= 50
GROUP BY pe.participant_id
ORDER BY pe.participant_id;
```

### 3. Document Performance Improvement
After optimization, insert the results into your `participant_performance_report` table.

## Success Criteria
- The query should execute significantly faster after your optimization
- All results should be correctly inserted into the report table
- Your optimization should use appropriate database indexes

## Important Notes
- Analyze the query execution plan to identify bottlenecks
- Focus on the most impactful optimizations
- Handle NULL values appropriately in calculations