"""
Custom evaluator functions for MCPMark Notion tasks.

These functions adapt verification logic from mcpmark/tasks/notion/*/verify.py
into the MCP-Universe evaluator framework.
"""
# pylint: disable=line-too-long,import-outside-toplevel,duplicate-code
from __future__ import annotations

from typing import Tuple
from mcpuniverse.evaluator.functions import compare_func


##################################################################################
# Company In A Box - Employee Onboarding
##################################################################################

@compare_func(name="mcpmark.notion.verify_employee_onboarding")
async def verify_employee_onboarding(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the employee onboarding system task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.company_in_a_box.employee_onboarding.verify import verify

    Checks:
    - Employee Onboarding Checklist database exists with correct schema
    - Database has at least 3 entries with all required properties filled
    - Onboarding Hub page exists with embedded database
    - Benefits Overview section has ≥3 linked mentions to benefit policy pages
    - 30-Day Timeline section has numbered list with ≥7 steps
    - Feedback Form section has ≥3 to-do items
    """
    from mcpuniverse.evaluator.mcpmark.notion.company_in_a_box.employee_onboarding.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Company In A Box - Goals Restructure
##################################################################################

@compare_func(name="mcpmark.notion.verify_goals_restructure")
async def verify_goals_restructure(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the goals restructure task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.company_in_a_box.goals_restructure.verify import verify

    Checks:
    - Company In A Box page exists
    - Current Goals section exists with 4 toggle blocks
    - New goal "🔄 Digital Transformation Initiative" is present
    - All existing goals converted to toggles with descriptions moved inside
    - No residual heading_3 blocks that weren't converted to toggles
    """
    from mcpuniverse.evaluator.mcpmark.notion.company_in_a_box.goals_restructure.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Company In A Box - Quarterly Review Dashboard
##################################################################################

@compare_func(name="mcpmark.notion.verify_quarterly_review_dashboard")
async def verify_quarterly_review_dashboard(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the quarterly review dashboard task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.company_in_a_box.quarterly_review_dashboard.verify import verify

    Checks:
    - Q4 2024 Business Review Dashboard page exists as child of Company In A Box
    - Callout block contains all three keywords: LATAM, Enterprise, Employee engagement
    - Four department section headings exist: Product, Marketing, Sales, Human Resources
    - Action Items database exists with correct schema (Task Name, Department, Priority, Status)
    - Database contains ≥5 action items with all fields filled
    - Priority options include High/Medium/Low
    """
    from mcpuniverse.evaluator.mcpmark.notion.company_in_a_box.quarterly_review_dashboard.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Computer Science Student Dashboard - Code Snippets Go
##################################################################################

@compare_func(name="mcpmark.notion.verify_code_snippets_go")
async def verify_code_snippets_go(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the code snippets Go task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.computer_science_student_dashboard.code_snippets_go.verify import verify

    Checks:
    - Computer Science Student Dashboard page exists
    - Go column exists between Python and JavaScript columns
    - Bold header 'Go' is present
    - Three Go code blocks with correct captions and content:
      - Basic Go program
      - For loop in Go
      - Function definition in Go
    """
    from mcpuniverse.evaluator.mcpmark.notion.computer_science_student_dashboard.code_snippets_go.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Computer Science Student Dashboard - Courses Internships Relation
##################################################################################

@compare_func(name="mcpmark.notion.verify_courses_internships_relation")
async def verify_courses_internships_relation(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the courses internships relation task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.computer_science_student_dashboard.courses_internships_relation.verify import verify

    Checks:
    - Computer Science Student Dashboard page exists
    - Courses and Internship search databases exist
    - Bidirectional relation properties configured correctly
    - 3 course pages with codes CS301, CS302, CS303 and all required properties
    - 2 internship pages for OpenAI and Google with all required properties
    - Relations correctly connect courses and internships in both directions
    """
    from mcpuniverse.evaluator.mcpmark.notion.computer_science_student_dashboard.courses_internships_relation.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Computer Science Student Dashboard - Study Session Tracker
##################################################################################

@compare_func(name="mcpmark.notion.verify_study_session_tracker")
async def verify_study_session_tracker(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the study session tracker task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.computer_science_student_dashboard.study_session_tracker.verify import verify

    Checks:
    - Computer Science Student Dashboard page exists
    - New 2025-01-29 date section exists with bold date mention
    - Date section positioned correctly after 2022-09-02 but before divider
    - Exactly 4 unchecked to-do items with correct text and emojis:
      - 🧠 Review algorithms for technical interview
      - 📚 Study database systems chapter 7
      - ⚡ Practice system design problems
      - 🎯 Complete data structures assignment
    """
    from mcpuniverse.evaluator.mcpmark.notion.computer_science_student_dashboard.study_session_tracker.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# IT Trouble Shooting Hub - Asset Retirement Migration
##################################################################################

@compare_func(name="mcpmark.notion.verify_asset_retirement_migration")
async def verify_asset_retirement_migration(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the asset retirement migration task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.it_trouble_shooting_hub.asset_retirement_migration.verify import verify

    Checks:
    - IT Trouble Shooting Hub page exists
    - IT Inventory and IT Asset Retirement Queue databases exist
    - Retirement queue database has correct schema with all required properties
    - Retirement Reason select options include: Expired License, Hardware Obsolete, Security Risk, User Offboarding
    - Database description is exactly "AUTO-GENERATED MIGRATION COMPLETED"
    - Expired/To be returned items moved from IT Inventory to retirement queue
    - Retirement Migration Log page exists with correct callout block
    """
    from mcpuniverse.evaluator.mcpmark.notion.it_trouble_shooting_hub.asset_retirement_migration.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# IT Trouble Shooting Hub - Security Audit Ticket
##################################################################################

@compare_func(name="mcpmark.notion.verify_security_audit_ticket")
async def verify_security_audit_ticket(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the security audit ticket task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.it_trouble_shooting_hub.security_audit_ticket.verify import verify

    Checks:
    - IT Trouble Shooting Hub page exists
    - IT Requests database exists
    - Security audit ticket with exact title "Quarterly Security Audit - Expired Assets Review"
    - Priority set to "High" and Due date set to "2023-06-22"
    - Bullet list contains expired inventory items in format: "<Serial> - <Tag> - <Recommendation>"
    - All expected serials present: 192371-8910/54, 32x11PIP, 76x87PCY, 36x10PIQ, 65XYQ/GB
    """
    from mcpuniverse.evaluator.mcpmark.notion.it_trouble_shooting_hub.security_audit_ticket.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# IT Trouble Shooting Hub - Verification Expired Update
##################################################################################

@compare_func(name="mcpmark.notion.verify_verification_expired_update")
async def verify_verification_expired_update(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the verification expired update task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.it_trouble_shooting_hub.verification_expired_update.verify import verify

    Checks:
    - IT Trouble Shooting Hub page exists
    - IT Homepage and IT Requests databases exist
    - Expired pages found in IT Homepage database (excluding IT Inventory)
    - Each expired page has callout block with warning icon ⚠️ and red background
    - Callout text contains "VERIFICATION EXPIRED - This page needs review and re-verification"
    - IT Request "Batch Verification Update Required" created with High priority and In progress status
    - Request body contains bullet list with mentions to all affected expired pages
    """
    from mcpuniverse.evaluator.mcpmark.notion.it_trouble_shooting_hub.verification_expired_update.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Japan Travel Planner - Daily Itinerary Overview
##################################################################################

@compare_func(name="mcpmark.notion.verify_daily_itinerary_overview")
async def verify_daily_itinerary_overview(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the daily itinerary overview task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.daily_itinerary_overview.verify import verify

    Checks:
    - Japan Travel Planner page exists
    - Daily Itinerary Overview child page created
    - Page structure with correct headings: 📅 Daily Itinerary Overview, 📊 Trip Summary, 🌅 Day 1, 🌆 Day 2, 🌃 Day 3
    - Trip summary paragraph with total activities visited count
    - To-do list items for each day with activity names and cities
    - Checked status matches visited status from Travel Itinerary database
    """
    from mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.daily_itinerary_overview.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Japan Travel Planner - Packing Progress Summary
##################################################################################

@compare_func(name="mcpmark.notion.verify_packing_progress_summary")
async def verify_packing_progress_summary(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the packing progress summary task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.packing_progress_summary.verify import verify

    Checks:
    - Japan Travel Planner page exists
    - Packing List database found
    - All Clothes items marked as packed except hat
    - SIM Card and Wallet entries checked
    - Packing Progress Summary section created with bold text
    - Statistics bullet points in format "Category: X/Y packed"
    - Correct statistics for all categories: Clothes, Electronics, Essentials, Miscellaneous, Shoes, Toiletries
    """
    from mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.packing_progress_summary.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Japan Travel Planner - Remove Osaka Itinerary
##################################################################################

@compare_func(name="mcpmark.notion.verify_remove_osaka_itinerary")
async def verify_remove_osaka_itinerary(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the remove Osaka itinerary task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.remove_osaka_itinerary.verify import verify

    Checks:
    - Japan Travel Planner page exists
    - Travel Itinerary database found
    - All OSAKA events after 6 PM on Day 1 and Day 2 removed
    - Specific items deleted: Rikuro's Namba Main Branch (7 PM Day 1), Shin Sekai "New World" (8 PM Day 2), Katsudon Chiyomatsu (7:30 PM Day 2), Ebisubashi Bridge (9 PM Day 1)
    - Items at or before 6 PM retained (e.g., Kuromon Ichiba Market at 6 PM)
    - No OSAKA items after 6 PM remain on Day 1 and Day 2
    """
    from mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.remove_osaka_itinerary.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Japan Travel Planner - Restaurant Expenses Sync
##################################################################################

@compare_func(name="mcpmark.notion.verify_restaurant_expenses_sync")
async def verify_restaurant_expenses_sync(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the restaurant expenses sync task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.restaurant_expenses_sync.verify import verify

    Checks:
    - Japan Travel Planner page exists
    - Travel Itinerary and Expenses databases found
    - Day 1 restaurants from Travel Itinerary identified
    - Corresponding expense entries created in Expenses database
    - Each expense entry has: restaurant name in Expense field, date set to 2025-01-01, amount set to $120, Category set to Dining
    - Comment field matches restaurant description from Japan Places to Visit database
    - All Day 1 restaurants have matching expense entries
    """
    from mcpuniverse.evaluator.mcpmark.notion.japan_travel_planner.restaurant_expenses_sync.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Online Resume - Layout Adjustment
##################################################################################

@compare_func(name="mcpmark.notion.verify_layout_adjustment")
async def verify_layout_adjustment(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the layout adjustment task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.online_resume.layout_adjustment.verify import verify

    Checks:
    - Online Resume page exists
    - Skills database removed from right column
    - Skills section added to left column under Languages
    - Skills formatted with correct icons based on skill level (✨✨ for >=50%, ✨ for <50%)
    - Work History and Education sections use black placeholder images
    - All expected skills present with correct formatting
    """
    from mcpuniverse.evaluator.mcpmark.notion.online_resume.layout_adjustment.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Online Resume - Projects Section Update
##################################################################################

@compare_func(name="mcpmark.notion.verify_projects_section_update")
async def verify_projects_section_update(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the projects section update task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.online_resume.projects_section_update.verify import verify

    Checks:
    - Online Resume page exists
    - Projects and Skills databases found
    - "Knitties eComm Website" project deleted
    - "Zapier Dashboard Redesign" project exists with correct properties
    - Project has correct description, date range, tags, phone, and URL
    - Enterprise tag has purple color
    - Current Focus section created after Projects database
    - Paragraph references highest skill from Skills database
    """
    from mcpuniverse.evaluator.mcpmark.notion.online_resume.projects_section_update.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Online Resume - Skills Development Tracker
##################################################################################

@compare_func(name="mcpmark.notion.verify_skills_development_tracker")
async def verify_skills_development_tracker(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the skills development tracker task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.online_resume.skills_development_tracker.verify import verify

    Checks:
    - New Online Resume page exists
    - Skills Development Tracker database created with correct schema
    - Database has required properties: Name, Current Skill, Current Proficiency, Target Proficiency, Gap, Learning Resources, Progress Notes
    - Target Proficiency property has percent format
    - Entries created for skills with proficiency < 70%
    - Entry names follow "Skill Name Development Plan" format
    - Callout block with blue background and 🎯 emoji after Skills section
    - Callout contains "Focus Areas:" with CSS + Basic JS, Webflow, and Rive
    """
    from mcpuniverse.evaluator.mcpmark.notion.online_resume.skills_development_tracker.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Online Resume - Work History Addition
##################################################################################

@compare_func(name="mcpmark.notion.verify_work_history_addition")
async def verify_work_history_addition(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the work history addition task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.online_resume.work_history_addition.verify import verify

    Checks:
    - Online Resume page exists
    - New "Research Assistant" work history entry added
    - Entry has correct title, date, and description
    - Title is bold, date is italic and gray, description is default color
    - Entry uses same image as Education section
    - Entry positioned correctly in Work History section
    """
    from mcpuniverse.evaluator.mcpmark.notion.online_resume.work_history_addition.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Python Roadmap - Expert Level Lessons
##################################################################################

@compare_func(name="mcpmark.notion.verify_expert_level_lessons")
async def verify_expert_level_lessons(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """Verify Expert Level chapter created with 4 lessons and complex prerequisite relationships."""
    from mcpuniverse.evaluator.mcpmark.notion.python_roadmap.expert_level_lessons.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Python Roadmap - Learning Metrics Dashboard
##################################################################################

@compare_func(name="mcpmark.notion.verify_learning_metrics_dashboard")
async def verify_learning_metrics_dashboard(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """Verify Learning Metrics Dashboard created with course statistics and completed topics."""
    from mcpuniverse.evaluator.mcpmark.notion.python_roadmap.learning_metrics_dashboard.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Self Assessment - FAQ Column Layout
##################################################################################

@compare_func(name="mcpmark.notion.verify_faq_column_layout")
async def verify_faq_column_layout(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the FAQ column layout task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.self_assessment.faq_column_layout.verify import verify

    Checks:
    - Self Assessment page exists
    - FAQ toggle block found
    - Column list exists inside FAQ toggle
    - No Q&A content outside column list
    - Exactly 2 columns in the column list
    - Each column contains exactly 2 Q&A pairs
    """
    from mcpuniverse.evaluator.mcpmark.notion.self_assessment.faq_column_layout.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Self Assessment - Hyperfocus Analysis Report
##################################################################################

@compare_func(name="mcpmark.notion.verify_hyperfocus_analysis_report")
async def verify_hyperfocus_analysis_report(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the hyperfocus analysis report task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.self_assessment.hyperfocus_analysis_report.verify import verify

    Checks:
    - Self Assessment page exists
    - Hyperfocus Analysis Report page exists and is positioned correctly
    - Database 'Hyperfocus Self-Assessment Worksheet' exists
    - Report contains callout with top 2 strategies
    - Session sections with proper headings and bullet points
    - All session data matches database entries
    """
    from mcpuniverse.evaluator.mcpmark.notion.self_assessment.hyperfocus_analysis_report.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Self Assessment - Numbered List Emojis
##################################################################################

@compare_func(name="mcpmark.notion.verify_numbered_list_emojis")
async def verify_numbered_list_emojis(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the numbered list emojis task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.self_assessment.numbered_list_emojis.verify import verify

    Checks:
    - Self Assessment page exists
    - No numbered list items remain (should be converted to emoji numbers)
    - All required emoji-numbered items are present
    - Items include hyperfocus session steps, references, and reflection questions
    """
    from mcpuniverse.evaluator.mcpmark.notion.self_assessment.numbered_list_emojis.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


@compare_func(name="mcpmark.notion.verify_priority_tasks_table")
async def verify_priority_tasks_table(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """Verify priority tasks table created with correct filtering and sorting by end date."""
    from mcpuniverse.evaluator.mcpmark.notion.team_projects.priority_tasks_table.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


@compare_func(name="mcpmark.notion.verify_swap_tasks")
async def verify_swap_tasks(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """Verify tasks swapped between person with most tasks and person with fewest tasks."""
    from mcpuniverse.evaluator.mcpmark.notion.team_projects.swap_tasks.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Standard Operating Procedure - Deployment Process SOP
##################################################################################

@compare_func(name="mcpmark.notion.verify_deployment_process_sop")
async def verify_deployment_process_sop(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the deployment process SOP task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.standard_operating_procedure.deployment_process_sop.verify import verify

    Checks:
    - Standard Operating Procedure page exists
    - SOP header information updated (title, date, department)
    - Purpose section with correct content
    - Context section with child page callouts
    - Terminologies section with exactly 4 items
    - Tools section with 2 child page callouts
    - Roles & responsibilities with exactly 4 items
    - Procedure section with exactly 3 numbered items
    """
    from mcpuniverse.evaluator.mcpmark.notion.standard_operating_procedure.deployment_process_sop.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Standard Operating Procedure - Section Organization
##################################################################################

@compare_func(name="mcpmark.notion.verify_section_organization")
async def verify_section_organization(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the section organization task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.standard_operating_procedure.section_organization.verify import verify

    Checks:
    - Standard Operating Procedure page exists
    - Correct section order: Roles & responsibilities < column_list < toggle < Procedure
    - Column layout with Tools in left column and Terminologies in right column
    - Tools column contains at least 2 link_to_page blocks
    - Toggle block contains Notion and Figma child pages
    - Original sections properly reorganized
    """
    from mcpuniverse.evaluator.mcpmark.notion.standard_operating_procedure.section_organization.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Toronto Guide - Change Color
##################################################################################

@compare_func(name="mcpmark.notion.verify_change_color")
async def verify_change_color(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the change color task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.toronto_guide.change_color.verify import verify

    Checks:
    - Toronto Guide page exists
    - All pink colors have been changed in callouts and database tags
    - Activities database tags (Parks, Neighbourhood) changed from pink
    - Food database tags (Middle Eastern, Jamaican, Indian) changed from pink
    - Cafes database tag (Food) changed from pink
    - Tag distributions maintained correctly
    """
    from mcpuniverse.evaluator.mcpmark.notion.toronto_guide.change_color.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg


##################################################################################
# Toronto Guide - Weekend Adventure Planner
##################################################################################

@compare_func(name="mcpmark.notion.verify_weekend_adventure_planner")
async def verify_weekend_adventure_planner(_x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the weekend adventure planner task.

    Adapted from: mcpuniverse.evaluator.mcpmark.notion.toronto_guide.weekend_adventure_planner.verify import verify

    Checks:
    - Toronto Guide page exists
    - Perfect Weekend Adventure child page created
    - Required headings present with correct structure
    - Beach activities bulleted list with correct items
    - Cultural dining numbered list with correct format
    - Coffee break spots toggle with unchecked to-do items
    - Weekend summary with correct counts
    - Divider and callout with pro tip
    """
    from mcpuniverse.evaluator.mcpmark.notion.toronto_guide.weekend_adventure_planner.verify import verify
    from mcpuniverse.evaluator.mcpmark.notion.utils import notion_utils

    # Get Notion client
    notion = notion_utils.get_notion_client()

    # Call the verify function
    passed, error_msg = verify(notion, None)
    return passed, error_msg
