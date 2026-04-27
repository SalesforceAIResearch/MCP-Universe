Please use FileSystem tools to finish the following task:

### Simple Grade Calculation

1. Read Student Data:

* Process all student basic_info.txt files from the database
* Extract scores for Chinese, Math, and English subjects

2. Calculate Basic Grades:

* Use simple grade scale: A (90+), B (80-89), C (70-79), D (60-69), F (<60)
* Apply this same scale to all subjects

### Generate Output Files

1. Create student_grades.csv:

* Columns: student_id, name, chinese_score, chinese_grade, math_score, math_grade, english_score, english_grade
* Must contain exactly each students
* Each students one row

2. Create grade_summary.txt:

* Total number of students processed
* Number of A's, B's, C's, D's, and F's for each subject
* Simple count of students with passing grades (A, B, C) vs failing grades (D, F) for each subjects
