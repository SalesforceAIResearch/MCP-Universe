Analyze employee retention patterns and identify factors contributing to turnover across the organization. The HR leadership team needs comprehensive insights to develop targeted retention strategies and reduce costly employee attrition.

## Your Tasks:

1. **Create the retention analysis table** — build a table called `employee_retention_analysis` in the `employees` schema with these exact columns:
   * `department_name` (varchar) — the department name
   * `total_employees_ever` (integer) — total number of employees who have ever worked in this department
   * `current_employees` (integer) — number of current employees in the department
   * `former_employees` (integer) — number of employees who left the department
   * `retention_rate` (decimal) — percentage of employees still with the company (current/total * 100)

2. **Create the high-risk employee identification table** — build a table called `high_risk_employees` in the `employees` schema with:
   * `employee_id` (bigint) — the employee's ID  
   * `full_name` (varchar) — concatenated first and last name
   * `current_department` (varchar) — current department name
   * `tenure_days` (integer) — days with the company
   * `current_salary` (integer) — current salary amount
   * `risk_category` (varchar) — risk level ('high_risk', 'medium_risk', 'low_risk')
   
   **Note**: Analyze only current employees (those with active salary records where to_date = '9999-01-01').

3. **Create the turnover trend analysis table** — build a table called `turnover_trend_analysis` in the `employees` schema with:
   * `departure_year` (integer) — year when employees left (extract from to_date of salary records)
   * `departures_count` (integer) — number of employees who left that year
   * `avg_tenure_days` (decimal) — average tenure in days for employees who left that year
   * `avg_final_salary` (decimal) — average final salary of departed employees that year

4. **Apply risk assessment criteria** for current employees:
   * **High risk**: Employees in departments with retention rate < 80% AND tenure < 1095 days (3 years)
   * **Medium risk**: Employees in departments with retention rate < 85% AND tenure < 1825 days (5 years)  
   * **Low risk**: All other current employees

5. **Analyze departure trends** — examine employees who left between 1985-2002, grouping by departure year.

6. **Handle final salary selection** — when calculating `avg_final_salary`, if an employee has multiple salary records with the same departure date, select the record with the latest start date. If there are still ties, select the record with the highest salary amount.

7. **Focus appropriately** — use current employees for risk analysis, all historical data for retention rates, and former employees for trend analysis.

The comprehensive analysis will help identify retention patterns, at-risk employees, and historical turnover trends to guide strategic workforce planning.
