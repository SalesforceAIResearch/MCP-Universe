Generate a comprehensive employee demographics and basic statistics report for the annual company overview. The HR team needs simple, clear statistical summaries about our workforce composition to include in the annual report and diversity initiatives.

## Your Tasks:

1. **Create the gender statistics table** — build a table called `gender_statistics` in the `employees` schema with these exact columns:
   * `gender` (varchar) — gender ('M' or 'F')
   * `total_employees` (integer) — total number of employees of this gender
   * `current_employees` (integer) — current employees of this gender (have active salary)
   * `percentage_of_workforce` (decimal) — percentage of current workforce

2. **Create the age group analysis table** — build a table called `age_group_analysis` in the `employees` schema with:
   * `age_group` (varchar) — age range ('20-29', '30-39', '40-49', '50-59', '60+')
   * `employee_count` (integer) — number of current employees in age group
   * `avg_salary` (decimal) — average current salary for age group
   * `avg_tenure_days` (decimal) — average days of service

3. **Create the birth month distribution table** — build a table called `birth_month_distribution` in the `employees` schema with:
   * `birth_month` (integer) — month number (1-12)
   * `month_name` (varchar) — month name ('January', 'February', etc.)
   * `employee_count` (integer) — total employees born in this month
   * `current_employee_count` (integer) — current employees born in this month

4. **Create the hiring year summary table** — build a table called `hiring_year_summary` in the `employees` schema with:
   * `hire_year` (integer) — year employees were hired
   * `employees_hired` (integer) — number of employees hired that year
   * `still_employed` (integer) — how many from that year are still employed
   * `retention_rate` (decimal) — percentage still employed (still_employed/employees_hired * 100)

5. **Apply age group classification** based on current age:
   * **20-29**: Ages 20-29
   * **30-39**: Ages 30-39  
   * **40-49**: Ages 40-49
   * **50-59**: Ages 50-59
   * **60+**: Ages 60 and above

6. **Calculate workforce composition** — determine current workforce demographics using employees with active salary records (to_date = '9999-01-01').

7. **Focus on basic statistics** — create simple counts, averages, and percentages that are easy to understand and verify.

The analysis will provide clear demographic insights for HR reporting and workforce planning.
