"""
Custom evaluator functions for MCPMark Playwright tasks.

These functions adapt verification logic from mcpmark/tasks/playwright/*/verify.py
into the MCP-Universe evaluator framework.

Argument conventions (per Evaluator.evaluate):
- compare_fn(x, value, op_args, context=...) is invoked as:
  - x: result from func-chain (first positional arg)
  - value: config.value (args[0])
  - op_args: config.op_args (args[1])
  - context: keyword-only in kwargs
"""
# pylint: disable=line-too-long,import-outside-toplevel,duplicate-code

from __future__ import annotations

from typing import Any, Tuple

from mcpuniverse.evaluator.functions import compare_func


def ensure_messages_json_exists(x: Any) -> None:
    """
    Ensure messages.json file exists for verification scripts.

    Many mcpmark verification scripts expect to read messages.json to get
    the agent's conversation history. In mcpuniverse, this file is not
    automatically created, so we create it here with the agent output.

    Args:
        x: Agent output (string or dict)
    """
    import json
    import os
    from pathlib import Path

    messages_path = os.getenv("MCP_MESSAGES")
    if not messages_path:
        return

    messages_file = Path(messages_path)
    if messages_file.exists():
        return  # File already exists, don't overwrite

    # Create a minimal messages.json with the agent output
    try:
        messages_file.parent.mkdir(parents=True, exist_ok=True)
        messages = [
            {
                "role": "assistant",
                "status": "completed",
                "type": "message",
                "content": [{"type": "text", "text": str(x)}]
            }
        ]
        with open(messages_file, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2)
    except (OSError, IOError, TypeError, ValueError) as e:
        # Log but don't fail - verification might still work
        import sys
        print(f"Warning: Failed to create messages.json: {e}", file=sys.stderr)


##################################################################################
# Playwright Eval Web - Extraction Table
##################################################################################

@compare_func(name="mcpmark.playwright.verify_extraction_table")
async def verify_extraction_table(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the extraction table task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright.eval_web.extraction_table.verify import verify

    Checks:
    - Model response contains CSV data extraction results
    - CSV format matches expected structure exactly
    - Header format matches "Title, Rating, Likes, Views, Replies"
    - Data rows match expected count (97 rows)
    - All columns have correct data types and format
    """
    from mcpuniverse.evaluator.mcpmark.playwright.eval_web.extraction_table.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Playwright Eval Web - Cloudflare Turnstile Challenge
##################################################################################

@compare_func(name="mcpmark.playwright.verify_cloudflare_turnstile_challenge")
async def verify_cloudflare_turnstile_challenge(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the cloudflare turnstile challenge task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright.eval_web.cloudflare_turnstile_challenge.verify import verify

    Checks:
    - Model response contains expected success message
    - Success message: "Authentication successful! Security challenge verified."
    - Model successfully completed the Cloudflare Turnstile challenge
    """
    from mcpuniverse.evaluator.mcpmark.playwright.eval_web.cloudflare_turnstile_challenge.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = verify()
    return passed, error_msg


##################################################################################
# Playwright Web Search - Birth of Arvinxu
##################################################################################

@compare_func(name="mcpmark.playwright.verify_birth_of_arvinxu")
async def verify_birth_of_arvinxu(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the birth of arvinxu web search task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright.web_search.birth_of_arvinxu.verify import verify_task

    Checks:
    - AI agent found the correct answer: "1995"
    - Exact match verification in AI responses
    - Proper parsing of messages.json
    """
    from mcpuniverse.evaluator.mcpmark.playwright.web_search.birth_of_arvinxu.verify import verify_task

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = verify_task()
    return passed, error_msg


##################################################################################
# Playwright Web Search - R1 Arxiv
##################################################################################

@compare_func(name="mcpmark.playwright.verify_r1_arxiv")
async def verify_r1_arxiv(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the r1 arxiv web search task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright.web_search.r1_arxiv.verify import verify_task

    Checks:
    - AI agent extracted correct Introduction content
    - Content matches expected content from content.txt exactly
    - Proper content comparison and validation
    """
    from mcpuniverse.evaluator.mcpmark.playwright.web_search.r1_arxiv.verify import verify_task
    from pathlib import Path
    import os

    # Get working directory
    messages_path = os.getenv("MCP_MESSAGES")
    if messages_path and Path(messages_path).exists():
        work_dir = Path(messages_path).parent.resolve()
    else:
        work_dir = Path(".").resolve()

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = verify_task(work_dir)
    return passed, error_msg


##################################################################################
# Playwright WebArena Reddit - AI Data Analyst
##################################################################################

@compare_func(name="mcpmark.playwright.verify_ai_data_analyst")
async def verify_ai_data_analyst(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the AI data analyst reddit task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.ai_data_analyst.verify import verify

    Checks:
    - Account AIDataAnalyst2025 can login with password SecurePass123!
    - Submission 'MachineLearning_Extraction' found in MachineLearning forum
    - All 7 required fields present in pipe-separated format
    - Data matches expected values from label.txt
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.ai_data_analyst.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Reddit - Budget Europe Travel
##################################################################################

@compare_func(name="mcpmark.playwright.verify_budget_europe_travel")
async def verify_budget_europe_travel(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the budget Europe travel reddit task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.budget_europe_travel.verify import verify

    Checks:
    - Account EuroTravelPlanner can login with correct credentials
    - Forum /f/BudgetEuropeTravel exists with correct properties
    - Wiki page exists with correct content
    - Post exists in forum with required content
    - Upvote on search result completed
    - User settings configured correctly
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.budget_europe_travel.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Reddit - BuyItForLife Research
##################################################################################

@compare_func(name="mcpmark.playwright.verify_buyitforlife_research")
async def verify_buyitforlife_research(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the buyitforlife research reddit task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.buyitforlife_research.verify import verify

    Checks:
    - Account buyitforlife_researcher can login with correct credentials
    - Submission 'Research Report for BuyItForLife' found in correct forum
    - All 14 required fields present and correct
    - Data matches expected values from label.txt
    - Posts ordered by upvotes (descending)
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.buyitforlife_research.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Reddit - LLM Research Summary
##################################################################################

@compare_func(name="mcpmark.playwright.verify_llm_research_summary")
async def verify_llm_research_summary(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the LLM research summary reddit task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.llm_research_summary.verify import verify

    Checks:
    - Account llm_analyst_2024 can login with correct credentials
    - Submission 'LLM Research Summary: GPT Discussions Analysis [2024]' found in MachineLearning forum
    - All 12 required fields present in Key:Value format
    - Data matches expected values from label.txt
    - Top 3 posts ordered by upvotes (descending)
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.llm_research_summary.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Reddit - Movie Reviewer Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_movie_reviewer_analysis")
async def verify_movie_reviewer_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the movie reviewer analysis reddit task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.movie_reviewer_analysis.verify import verify

    Checks:
    - Account movie_reviewer_2024 can login with correct credentials
    - Submission 'Wonderful Movies Analysis: Community Favorites [2024]' found in movies forum
    - All 13 required fields present in Key|Value format
    - Data matches expected values from label.txt
    - Rittenhouse Square data and image posts analysis completed
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.movie_reviewer_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Reddit - NBA Statistics Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_nba_statistics_analysis")
async def verify_nba_statistics_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the NBA statistics analysis reddit task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.nba_statistics_analysis.verify import verify

    Checks:
    - Account NBA_DataAnalyst_2024 can login with correct credentials
    - Submission 'Statistical Analysis: NBA Content Engagement on This Forum' found in sports forum
    - All 21 required fields present in Key|Value format
    - Data matches expected values from label.txt
    - Top 5 NBA posts identified and BCLetsRide69's total posts documented
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.nba_statistics_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Reddit - Routine Tracker Forum
##################################################################################

@compare_func(name="mcpmark.playwright.verify_routine_tracker_forum")
async def verify_routine_tracker_forum(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the routine tracker forum reddit task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.routine_tracker_forum.verify import verify

    Checks:
    - Account RoutineTracker2025 can login with correct credentials
    - Post 'My 5-Step Morning Routine That Increased My Productivity by 200%' found in LifeProTips forum
    - Post content matches expected content from most upvoted comment
    - Calendar post upvoted (count: 1)
    - Stovetop post upvoted (count: 1)
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.reddit.routine_tracker_forum.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping - Advanced Product Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_advanced_product_analysis")
async def verify_advanced_product_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the advanced product analysis shopping task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.advanced_product_analysis.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 5 lines
    - All required fields present: GingerAleSKU, IntelNUCSKU, CartTotal, ReviewCount, LatestReviewer
    - Data matches expected values from label.txt
    - Price format validation and exact SKU matching
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.advanced_product_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping - Gaming Accessories Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_gaming_accessories_analysis")
async def verify_gaming_accessories_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the gaming accessories analysis shopping task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.gaming_accessories_analysis.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 8 lines
    - All required fields present: CheapestReviewedPrice, N64Subtotal, CheckoutEmail, Products70Plus
    - Data matches expected values from label.txt
    - Price format validation and email matching
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.gaming_accessories_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping - Health Routine Optimization
##################################################################################

@compare_func(name="mcpmark.playwright.verify_health_routine_optimization")
async def verify_health_routine_optimization(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the health routine optimization shopping task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.health_routine_optimization.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 14 lines
    - All required fields present: Battery1Price, Battery2Price, InitialSubtotal, FinalSubtotal
    - Data matches expected values from label.txt
    - Price format validation for all monetary fields
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.health_routine_optimization.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping - Holiday Baking Competition
##################################################################################

@compare_func(name="mcpmark.playwright.verify_holiday_baking_competition")
async def verify_holiday_baking_competition(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the holiday baking competition shopping task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.holiday_baking_competition.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 7 lines
    - All required fields present: SecondGingerbreadSKU, CartSubtotalAfterUpdate, TotalCartItems, etc.
    - Data matches expected values from label.txt
    - Price format validation and SKU matching with complex colon-separated fields
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.holiday_baking_competition.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping - Multi Category Budget Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_multi_category_budget_analysis")
async def verify_multi_category_budget_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the multi category budget analysis shopping task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.multi_category_budget_analysis.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 11 lines
    - All required fields present: chocolate_products, tabletop_product, chocolate_sum, etc.
    - Data matches expected values from label.txt
    - Price format validation and complex product list parsing
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.multi_category_budget_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping - Printer Keyboard Search
##################################################################################

@compare_func(name="mcpmark.playwright.verify_printer_keyboard_search")
async def verify_printer_keyboard_search(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the printer keyboard search shopping task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.printer_keyboard_search.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 6 lines
    - All required fields present: PrinterPrice, PrinterSKUID, KeyboardPrice, KeyboardSKUID, etc.
    - Data matches expected values from label.txt
    - Price format validation and SKU matching
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.printer_keyboard_search.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping - Running Shoes Purchase
##################################################################################

@compare_func(name="mcpmark.playwright.verify_running_shoes_purchase")
async def verify_running_shoes_purchase(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the running shoes purchase shopping task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.running_shoes_purchase.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 5 lines
    - All required fields present: Price, SKUID, NumberOfReviews, ReviewRating, Subtotal
    - Data matches expected values from label.txt
    - Price format validation and SKU matching with tolerance for calculations
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping.running_shoes_purchase.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping Admin - Customer Segmentation Setup
##################################################################################

@compare_func(name="mcpmark.playwright.verify_customer_segmentation_setup")
async def verify_customer_segmentation_setup(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the customer segmentation setup shopping admin task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.customer_segmentation_setup.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 5 lines
    - All required fields present: PremiumEuropeGroup, FinalCustomers, LastOrderCustomer, etc.
    - Data matches expected values from label.txt
    - Browser verification: Premium Europe customer group exists with Retail Customer tax class
    - Customer 'isabella.romano@premium.eu' found in system
    - Dashboard Last Orders section accessible
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.customer_segmentation_setup.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping Admin - Fitness Promotion Strategy
##################################################################################

@compare_func(name="mcpmark.playwright.verify_fitness_promotion_strategy")
async def verify_fitness_promotion_strategy(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the fitness promotion strategy shopping admin task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.fitness_promotion_strategy.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with flexible line count
    - All required fields present: Bestseller1, Bestseller2, Bestseller3, LowestInventoryProduct, etc.
    - Data matches expected values from label.txt
    - Complex field validation for colon-separated values (name:price:quantity:sku:inventory:status)
    - Price format validation and inventory number matching
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.fitness_promotion_strategy.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping Admin - Marketing Customer Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_marketing_customer_analysis")
async def verify_marketing_customer_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the marketing customer analysis shopping admin task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.marketing_customer_analysis.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 9 lines
    - All required fields present: Top2SearchTerms, EmailVerification, CouponCodes, TopProduct, etc.
    - Data matches expected values from label.txt
    - Browser verification: Two specific customers created in Magento Admin
    - Customer validation with email, name, group, and website requirements
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.marketing_customer_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping Admin - NY Expansion Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_ny_expansion_analysis")
async def verify_ny_expansion_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the NY expansion analysis shopping admin task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.ny_expansion_analysis.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 16 expected keys
    - All required fields present: Lifetime_Sales_Amount, Cheap_Bestseller_Name, Second_Bestseller_Price, etc.
    - Data matches expected values from label.txt
    - Complex field validation for price/amount fields, tax rates, Yes/No fields
    - Flexible validation for descriptive fields and order status options
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.ny_expansion_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping Admin - Products Sales Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_products_sales_analysis")
async def verify_products_sales_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the products sales analysis shopping admin task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.products_sales_analysis.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 10 lines
    - All required fields present: YogaProducts, WH11Price, ZeroQuantityProducts, etc.
    - Data matches expected values from label.txt
    - Complex field validation for product:quantity format, price format, email validation
    - Special handling for LowestProduct field with name:quantity format
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.products_sales_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping Admin - Sales Inventory Analysis
##################################################################################

@compare_func(name="mcpmark.playwright.verify_sales_inventory_analysis")
async def verify_sales_inventory_analysis(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the sales inventory analysis shopping admin task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.sales_inventory_analysis.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 13 lines
    - All required fields present: SpriteProducts, Quantity100Products, WS12Info, etc.
    - Data matches expected values from label.txt
    - Complex field validation for name:price format, order ID validation, customer:amount format
    - Special handling for position format, date flexibility, and invoice validation
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.sales_inventory_analysis.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg


##################################################################################
# Playwright WebArena Shopping Admin - Search Filtering Operations
##################################################################################

@compare_func(name="mcpmark.playwright.verify_search_filtering_operations")
async def verify_search_filtering_operations(x: dict, *_args, **_kwargs) -> Tuple[bool, str]:
    """
    Verify the search filtering operations shopping admin task.

    Adapted from: mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.search_filtering_operations.verify import verify

    Checks:
    - Model response contains <answer>...</answer> format with 13 lines
    - All required fields present: TankSearchCount, ZeroResultsCount, HighestUseTerm, etc.
    - Data matches expected values with specific validation rules
    - Complex validation for term:uses format, term:results format, product:quantity format
    - Specific expected values for search terms, counts, and bestseller positions
    """
    from mcpuniverse.evaluator.mcpmark.playwright_webarena.shopping_admin.search_filtering_operations.verify import verify

    # Ensure messages.json exists for verification script
    ensure_messages_json_exists(x)

    # Call the verify function
    passed, error_msg = await verify()
    return passed, error_msg
