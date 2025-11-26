Using Notion Tools. Complete the SOP template (a notion page titled 'Standard Operating Procedure') by filling in all sections with comprehensive, interconnected content for a "Software Deployment Process" SOP, ensuring all cross-references, terminologies, and procedural steps are properly linked and validated.

**Task Requirements:**

1. **Update the SOP header information** (in the left column):
   - Change the heading_1 "SOP Title" text to "Software Deployment Process"
   - Update the paragraph "Created 2023-10-25" to "Created 2025-01-19"
   - Update the paragraph "Responsible department:" to "Responsible department: DevOps Engineering Team"
   - Update the People team page's callout to: "DevOps Engineering Team Wiki - Contains team contact information, escalation procedures, and deployment schedules. Access required for all deployment activities."

2. **Fill the Purpose section** with exactly this content:
   - Replace the placeholder paragraph (starts with "↓ Summarize the procedure") with: "This SOP defines the standardized process for deploying software applications to production environments, ensuring zero-downtime deployments, proper rollback procedures, and compliance with security protocols. This procedure applies to all production deployments and must be followed by all engineering teams."

3. **Complete the Context section** with:
   - Replace the placeholder paragraph (starts with "↓ Add any related and useful information") with: "Software deployments are critical operations that can impact system availability and user experience. This process has been developed based on industry best practices and our incident response learnings from Q3 2023. All deployments must go through automated testing pipelines and require approval from designated reviewers."
   - Update all THREE child_pages under the "Relevant Docs" toggle:
     - First child_page callout (Contacting IT): "Change Management Policy (SOP-001) - Defines approval workflows and change review processes for all production modifications."
     - Second child_page callout (Team lunches): "Incident Response Procedures (SOP-003) - Emergency procedures for handling deployment failures and system outages."
     - Third child_page callout (Sending swag): "Security Compliance Guidelines (SOP-007) - Security requirements and validation steps for production deployments."

4. **Define comprehensive Terminologies** by:
   - Replace the placeholder paragraph (starts with "↓ Add any unfamiliar or domain specific words") with: "Essential deployment terminology for team understanding:"
   - Replace the existing bulleted_list_item "Term: The definition of the term" with these four exact items:
     - "Blue-Green Deployment: A deployment strategy that maintains two identical production environments"
     - "Rollback Window: The maximum time allowed to revert a deployment (30 minutes)"  
     - "Smoke Test: Initial verification tests run immediately after deployment"
     - "Production Gateway: The approval checkpoint before production release"

5. **Populate Tools section** with:
   - Replace the placeholder paragraph (starts with "↓ Add any relevant tools") with: "Critical tools required for deployment operations:"
   - Update the TWO existing child_pages:
     - First child_page callout: "Jenkins CI/CD Pipeline - Primary deployment automation tool with integrated testing and approval workflows. Required for all automated deployments."
     - Second child_page callout: "Kubernetes Dashboard - Container orchestration monitoring and management interface for deployment verification and rollback operations."

6. **Complete Roles & responsibilities** with:
   - Replace the placeholder paragraph (starts with "↓ Define who will be executing") with: "The following roles are essential for successful deployment execution:"
   - Replace the existing empty bulleted_list_item with these four exact items:
     - "DevOps Engineer: Executes deployment, monitors system health, initiates rollbacks if needed"
     - "Lead Developer: Reviews code changes, approves deployment package, validates functionality"  
     - "QA Engineer: Verifies smoke tests, confirms user acceptance criteria"
     - "Security Officer: Validates security compliance, approves security-sensitive deployments"

7. **Create detailed Procedure section** with:
   - Replace the placeholder paragraph (starts with "↓ Create a step by step procedure") with: "Follow these steps in sequence. Do not skip steps or perform them out of order."
   - Replace the THREE existing numbered_list_items with:
     - "Pre-deployment: Verify all automated tests pass, obtain required approvals from Lead Developer and Security Officer, confirm rollback plan is documented and tested"
     - "Deployment execution: Deploy to staging environment first, run comprehensive smoke tests, obtain final Production Gateway approval, deploy to production using blue-green strategy"
     - "Post-deployment: Monitor system metrics for minimum 30 minutes, validate all functionality using automated tests, document deployment results in change log, notify all stakeholders via deployment notification system"