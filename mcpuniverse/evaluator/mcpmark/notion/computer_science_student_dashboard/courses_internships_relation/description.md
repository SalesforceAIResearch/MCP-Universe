Your goal is to connect the `Courses` and `Internship search` databases inside the **Computer Science Student Dashboard** page and populate them with sample data that can be verified automatically.

**Task Requirements:**

1. In the **Courses** database, add a new **relation** property named **Related Internships** that points to the **Internship search** database.
2. Ensure the relation is **bidirectional** by adding a relation property in the **Internship search** database named **Relevant Courses** that points back to the **Courses** database.
3. Create **exactly three** new pages in the **Courses** database with realistic computer-science course data.  Each course page must include **all** of the following properties and values:
   • **Code** (text) – unique codes `CS301`, `CS302`, and `CS303` respectively  
   • **Name** (text) – pick appropriate names (e.g., *Computer Networks*, *Operating Systems*, *Machine Learning*)  
   • **Credit** (number) – any positive integer  
   • **Status** (status) – choose from `Planned`, `In Progress`, or `Completed`  
   • **Related Internships** (relation) – link to at least one internship created in step4.
4. Create **exactly two** new pages in the **Internship search** database with complete application information.  Each internship page must include **all** of the following properties and values:
   • **Company** (text) – `OpenAI` and `Google` respectively  
   • **Role** (text) – `Machine Learning Intern` and `Software Engineering Intern`  
   • **Status** (status) – set to `Interested`  
   • **Relevant Courses** (relation) – link to one or more of the courses created in step3.
5. Every course created in step3 must be linked to at least one internship from step4 **and** every internship must be linked back to at least one course.

The task is considered complete when the relation properties exist, the specified course and internship pages are present with the exact values above, and the relations correctly connect the two databases in both directions.