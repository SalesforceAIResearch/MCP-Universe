Create a comprehensive employee performance evaluation system that analyzes career progression patterns and salary equity across our organization. The executive team needs data-driven insights for upcoming promotion decisions and salary adjustment planning.

## Your Tasks:

1. **Create the employee performance analysis table** — build a table called `employee_performance_analysis` in the `employees` schema with these exact columns:
   * `employee_id` (bigint) — the employee's ID
   * `performance_category` (varchar) — classification of employee performance ('high_achiever', 'steady_performer', 'needs_attention')
   * `salary_growth_rate` (decimal) — percentage salary increase from first salary record to current
   * `days_of_service` (integer) — total days with the company
   * `promotion_count` (integer) — number of different titles held

2. **Analyze only current employees** — focus on employees who currently have active salary records (to_date = '9999-01-01').

3. **Apply performance classification rules**:
   * **High achievers**: Salary growth rate > 40% AND more than 1 title held
   * **Needs attention**: Salary growth rate < 15% AND more than 3650 days of service (10 years)
   * **Steady performers**: All other current employees (default category)

4. **Create the department salary analysis table** — build a table called `department_salary_analysis` in the `employees` schema with:
   * `department_name` (varchar) — the department name
   * `avg_current_salary` (decimal) — average current salary in the department (only current employees)
   * `employee_count` (integer) — total current employees in the department
   * `salary_range_spread` (integer) — difference between max and min salary (current employees only)

5. **Calculate salary equity metrics** — populate the department table with current salary statistics for active employees only to identify potential pay equity issues across departments.

The analysis should help leadership make informed decisions about promotions, salary adjustments, and talent retention strategies.