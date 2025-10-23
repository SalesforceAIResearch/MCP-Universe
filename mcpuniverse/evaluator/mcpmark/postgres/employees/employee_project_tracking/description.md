Create and manage a comprehensive employee project tracking system using database schema design and data manipulation operations. The IT team needs you to build the database structure from scratch and populate it with specific initial data to support project management workflows.

## Your Tasks:

1. **Create the project tracking tables** — build three new tables in the `employees` schema:
   
   **Table 1: `employee_projects`**
   * `project_id` (integer, primary key, auto-increment)
   * `project_name` (varchar(100), not null)
   * `start_date` (date, not null)
   * `end_date` (date)
   * `budget` (decimal(10,2))
   * `status` (varchar(20), default 'active')

   **Table 2: `project_assignments`**
   * `assignment_id` (integer, primary key, auto-increment)
   * `employee_id` (bigint, not null)
   * `project_id` (integer, not null)
   * `role` (varchar(50), not null)
   * `allocation_percentage` (integer, check constraint: between 1 and 100)
   * `assigned_date` (date, not null)

   **Table 3: `project_milestones`**
   * `milestone_id` (integer, primary key, auto-increment)
   * `project_id` (integer, not null)
   * `milestone_name` (varchar(100), not null)
   * `due_date` (date, not null)
   * `completed` (boolean, default false)

2. **Add foreign key relationships**:
   * `project_assignments.employee_id` → `employees.employee.id`
   * `project_assignments.project_id` → `employees.employee_projects.project_id`
   * `project_milestones.project_id` → `employees.employee_projects.project_id`

3. **Create performance indexes**:
   * Index named `idx_projects_status` on `employee_projects.status`
   * Composite index named `idx_assignments_emp_proj` on `project_assignments(employee_id, project_id)`
   * Index named `idx_milestones_due_date` on `project_milestones.due_date`

4. **Insert exactly this initial data**:
   
   **Into `employee_projects`:**
   * Project 1: name='Database Modernization', start_date='2024-01-15', end_date='2024-06-30', budget=250000.00, status='active'
   * Project 2: name='Employee Portal Upgrade', start_date='2024-02-01', end_date='2024-05-15', budget=180000.00, status='active'  
   * Project 3: name='HR Analytics Dashboard', start_date='2023-11-01', end_date='2024-01-31', budget=120000.00, status='active'

   **Into `project_assignments` (assign ALL current employees):**
   * All employees from Development department → Project 1 ('Database Modernization'), role='Developer', allocation=80%
   * All employees from Human Resources department → Project 2 ('Employee Portal Upgrade'), role='Business Analyst', allocation=60%
   * All employees from Marketing department → Project 3 ('HR Analytics Dashboard'), role='Marketing Specialist', allocation=40%
   * All employees from Finance department → Project 1 ('Database Modernization'), role='Financial Analyst', allocation=30%
   * All employees from Sales department → Project 2 ('Employee Portal Upgrade'), role='Sales Representative', allocation=50%
   * All employees from Research department → Project 3 ('HR Analytics Dashboard'), role='Research Analyst', allocation=70%
   * All employees from Production department → Project 1 ('Database Modernization'), role='Production Coordinator', allocation=45%
   * All employees from Quality Management department → Project 2 ('Employee Portal Upgrade'), role='QA Specialist', allocation=85%
   * All employees from Customer Service department → Project 3 ('HR Analytics Dashboard'), role='Customer Success', allocation=35%
   * All employees should have assigned_date='2024-01-01'

   **Into `project_milestones`:**
   * Project 1: 'Design Phase Complete' due '2024-03-01', 'Implementation Complete' due '2024-05-15'
   * Project 2: 'UI/UX Approval' due '2024-03-15', 'Beta Testing' due '2024-04-30'
   * Project 3: 'Data Collection' due '2023-12-15', 'Dashboard Launch' due '2024-01-25'

5. **Perform these exact data updates**:
   * Update Project 3 ('HR Analytics Dashboard') status to 'completed'
   * Increase budget by 15% for all projects with status 'active'
   * Mark the milestone 'Data Collection' as completed (set completed = true)

6. **Add new column to `employee_projects`**:
   * Add `priority` column (varchar(10)) with check constraint allowing only 'low', 'medium', 'high'
   * Update all existing projects: set priority='high' for 'Database Modernization', priority='medium' for others
