Create a comprehensive skills audit system by performing the following tasks:

**Task Requirements:**
1. Create a new database named "Skills Development Tracker" as a child database in the main resume page with the following properties:
   - Name (title property)
   - Current Skill (relation to Skills database)
   - Current Proficiency (rollup from related skill's "Skill Level" property)
   - Target Proficiency (number property with format "percent")
   - Gap (formula: Target Proficiency - Current Proficiency)
   - Learning Resources (rich text property)
   - Progress Notes (rich text property)

2. Populate the Skills Development Tracker database with entries for all skills that have a proficiency level below 70% (0.7):
   - For each qualifying skill, create an entry with:
     - Name: "[Skill Name] Development Plan"
     - Link to the corresponding skill in Skills database
     - Target Proficiency: Set to Current + 25% (capped at 95%)
     - Learning Resources: "Online courses and practice projects"
     - Progress Notes: "Initial assessment completed"

3. Create a callout block immediately after the Skills section (after the Skills database) with:
   - Background color: blue_background
   - Icon: 🎯 (target emoji)
   - Content: "Focus Areas: [3 skills with lowest current proficiency]"