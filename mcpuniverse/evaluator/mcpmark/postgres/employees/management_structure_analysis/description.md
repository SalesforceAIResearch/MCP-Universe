Conduct a comprehensive management structure analysis to evaluate leadership effectiveness and organizational hierarchy. The executive team needs insights into management tenure, span of control, and leadership transitions to optimize the management structure and succession planning.

## Your Tasks:

1. **Create the manager profile table** — build a table called `manager_profile` in the `employees` schema with these exact columns:
   * `manager_id` (bigint) — the manager's employee ID
   * `manager_name` (varchar) — concatenated first and last name
   * `current_department` (varchar) — current department they manage (NULL if not current)
   * `management_periods` (integer) — total number of management assignments (including multiple periods in same department)
   * `current_manager` (boolean) — whether they are currently a manager

2. **Create the department leadership table** — build a table called `department_leadership` in the `employees` schema with:
   * `department_name` (varchar) — the department name
   * `current_manager_name` (varchar) — current manager's full name
   * `manager_start_date` (date) — when current manager started
   * `total_historical_managers` (integer) — total number of managers this department has had

3. **Create the management transition table** — build a table called `management_transitions` in the `employees` schema with:
   * `department_name` (varchar) — the department name
   * `transition_year` (integer) — year when management changed
   * `outgoing_manager` (varchar) — previous manager's name
   * `incoming_manager` (varchar) — new manager's name ('No Successor' if department had no immediate replacement)
   * `transition_gap_days` (integer) — days between managers (0 if immediate or no successor)

4. **Create the span of control table** — build a table called `span_of_control` in the `employees` schema with:
   * `manager_id` (bigint) — the manager's employee ID
   * `manager_name` (varchar) — manager's full name
   * `department_name` (varchar) — department they manage
   * `total_employees` (integer) — total employees in their department
   * `current_employees` (integer) — current active employees in department
   * `management_load` (varchar) — assessment ('light', 'moderate', 'heavy') based on current employees

5. **Apply management load classification**:
   * **Light**: < 5,000 current employees
   * **Moderate**: 5,000 - 15,000 current employees
   * **Heavy**: > 15,000 current employees

6. **Focus on current managers only** for span of control analysis — use managers with active management roles (to_date = '9999-01-01').

7. **Track all management history** for profiles and transitions — include both current and former managers to understand complete leadership evolution.

The analysis will provide insights into management effectiveness, departmental stability, and organizational structure optimization opportunities.
