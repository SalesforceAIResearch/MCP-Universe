Manage employee hierarchy and customer assignments through systematic CRUD operations.

## Your Mission:

Chinook needs to reorganize their employee structure and reassign customer relationships. Complete a series of precise database modifications to update the employee hierarchy.

## Tasks to Complete:

### 1. **INSERT: Add New Employees**
Insert exactly 2 new employees into the Employee table:
- EmployeeId: 9, FirstName: 'Sarah', LastName: 'Johnson', Title: 'Sales Support Agent', ReportsTo: 2, BirthDate: '1985-03-15', HireDate: '2009-01-10', Address: '123 Oak Street', City: 'Calgary', State: 'AB', Country: 'Canada', PostalCode: 'T2P 5G3', Phone: '+1 (403) 555-0123', Fax: '+1 (403) 555-0124', Email: 'sarah.johnson@chinookcorp.com'
- EmployeeId: 10, FirstName: 'Mike', LastName: 'Chen', Title: 'Sales Support Agent', ReportsTo: 2, BirthDate: '1982-08-22', HireDate: '2009-01-10', Address: '456 Pine Ave', City: 'Calgary', State: 'AB', Country: 'Canada', PostalCode: 'T2P 5G4', Phone: '+1 (403) 555-0125', Fax: '+1 (403) 555-0126', Email: 'mike.chen@chinookcorp.com'

### 2. **UPDATE: Modify Existing Employee Information**
- Change Andrew Adams (EmployeeId = 1) title from 'General Manager' to 'CEO'
- Update Nancy Edwards (EmployeeId = 2) phone number to '+1 (403) 555-9999'
- Change all employees with Title = 'IT Staff' to have Title = 'IT Specialist'

### 3. **UPDATE: Reassign Some Customers to New Employees**
- Update customers with CustomerId 1, 2, 3 to have SupportRepId = 9 (Sarah Johnson)
- Update customers with CustomerId 4, 5, 6 to have SupportRepId = 10 (Mike Chen)


### 4. **UPDATE: Reorganize Reporting Structure**
- Change Sarah Johnson (EmployeeId = 9) to report to Andrew Adams (EmployeeId = 1) instead of Nancy Edwards
- Change Mike Chen (EmployeeId = 10) to also report to Andrew Adams (EmployeeId = 1)

### 5. **INSERT: Create Employee Performance Table**
Create a new table called `employee_performance`:
- `employee_id` (integer, foreign key to Employee)
- `customers_assigned` (integer)
- `performance_score` (decimal)

Insert records for employees 9 and 10 by calculating their actual customer assignments:
- Sarah Johnson: calculate actual number of customers assigned to her, performance score 4.5
- Mike Chen: calculate actual number of customers assigned to him, performance score 4.2

### 6. **DELETE: Remove IT Department Employee**
- Delete Robert King (EmployeeId = 7) from the Employee table
- Before deletion, handle all relationships:
  - Find who Robert reports to and reassign any employees who report to Robert to report to Robert's manager instead
  - Find all customers assigned to Robert as their support rep and reassign them to Robert's manager

### 7. **UPDATE: Promote Remaining IT Staff**
- Promote Laura Callahan (EmployeeId = 8) from 'IT Specialist' to 'Senior IT Specialist'  
- Update her salary information by adding a new column `salary` to Employee table (decimal type)
- Set Laura's salary to 75000.00 and all other employees to 50000.00

### 8. **Final Verification Query**
Execute this exact query to verify all changes:
```sql
SELECT 
    COUNT(*) as total_employees,
    COUNT(CASE WHEN "Title" = 'CEO' THEN 1 END) as ceo_count,
    COUNT(CASE WHEN "Title" = 'IT Specialist' THEN 1 END) as it_specialist_count,
    COUNT(CASE WHEN "ReportsTo" = 1 THEN 1 END) as reports_to_ceo
FROM "Employee";
```

Expected result: total_employees = 9, ceo_count = 1, it_specialist_count = 0, reports_to_ceo = 4

## Business Rules:
* Use exact EmployeeId values as specified
* Maintain referential integrity between Employee and Customer tables
* All phone numbers must include country code format
* Email addresses must follow the pattern firstname.lastname@chinookcorp.com

## Expected Outcome:
The database should have exactly 10 employees total, with the new hierarchy structure in place and customer assignments updated accordingly.