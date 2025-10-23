Design a comprehensive reporting and automation system for executive dashboard and real-time monitoring. The executive team needs automated reports, data views, and trigger-based notifications to track key business metrics without manual intervention.

## Your Tasks:

1. **Create executive summary views** — build three materialized views in the `employees` schema:
   
   **View 1: `exec_department_summary`**
   * `department_name` (varchar) — department name
   * `total_employees` (integer) — current active employee count
   * `avg_salary` (decimal) — average current salary
   * `total_payroll` (bigint) — total monthly payroll cost
   * `manager_name` (varchar) — current department manager name

   **View 2: `exec_hiring_trends`**  
   * `hire_year` (integer) — year employees were hired
   * `employees_hired` (integer) — number hired that year
   * `avg_starting_salary` (decimal) — average first salary of hires that year
   * `retention_rate` (decimal) — percentage still employed
   * `top_hiring_department` (varchar) — department that hired the most that year

   **View 3: `exec_salary_distribution`**
   * `salary_band` (varchar) — salary ranges ('30K-50K', '50K-70K', '70K-90K', '90K-110K', '110K+')  
   * `employee_count` (integer) — employees in this salary band
   * `percentage_of_workforce` (decimal) — percentage of total workforce
   * `most_common_title` (varchar) — most frequent job title in this band

2. **Create stored procedure for report generation**:
   
   **Procedure: `generate_monthly_report(report_date DATE)`**
   * Create a table `monthly_reports` with columns: report_id (auto-increment), report_date, department_count, total_employees (current active employees only), avg_salary, generated_at
   * Insert one summary record using the report_date as identifier and current database statistics (not historical data for that date)
   * Return the generated report_id

3. **Create notification triggers**:
   
   **Trigger: `high_salary_alert`**
   * Fires when a new salary record is inserted with amount > 120000
   * Inserts alert into `salary_alerts` table with: employee_id, salary_amount, alert_date, status='new'

4. **Insert test data to verify triggers**:
   * Update employee 10001's current salary: first set their current salary record to_date='2024-01-31', then insert new salary record with amount 125000, from_date='2024-02-01', to_date='9999-01-01'
   * Refresh all materialized views after inserting new data to ensure they reflect the updated information

5. **Execute the stored procedure**:
   * Call `generate_monthly_report('2024-01-01')` to create January report
   * Query the generated report to verify execution

6. **Create performance indexes**:
   * Index on `salary_alerts.status` for alert processing
   * Composite index on `monthly_reports(report_date, department_count)` for trend analysis