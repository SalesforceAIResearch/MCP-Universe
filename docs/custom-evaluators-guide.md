# Custom Evaluators Implementation Guide

This guide provides comprehensive documentation for implementing custom evaluators in MCPUniverse. Evaluators are essential components that assess agent performance against specific criteria and validation rules.

## Table of Contents

1. [Evaluator System Overview](#evaluator-system-overview)
2. [Architecture and Interface](#architecture-and-interface)
3. [Function Types and Decorators](#function-types-and-decorators)
4. [Implementation Steps](#implementation-steps)
5. [Evaluation Functions](#evaluation-functions)
6. [Comparison Functions](#comparison-functions)

## Evaluator System Overview

The evaluator system is designed to validate agent outputs against predefined criteria. It consists of two main function types:

1. **Evaluation Functions**: Transform and extract data from agent responses
2. **Comparison Functions**: Compare processed data against expected values

### Key Components

- **Evaluator Class**: Main evaluation orchestrator
- **EvaluatorConfig**: Configuration specification for evaluation rules
- **EvaluationResult**: Output containing evaluation results and reasoning
- **FunctionResult**: Wrapper for function outputs in the evaluation pipeline

### System Architecture

```
Agent Output → Evaluation Functions → Comparison Functions → EvaluationResult
     ↓              ↓                      ↓                    ↓
   Raw JSON    Data Extraction        Value Validation      Pass/Fail + Reason
```

## Architecture and Interface

### Core Classes

#### EvaluatorConfig
```python
class EvaluatorConfig(BaseModel):
    func: str          # Function chain, e.g., "json -> get(key) -> len"
    op: str = ""       # Comparison operator, e.g., "=", "<", "contains"
    value: Any = None  # Expected value for comparison
    op_args: Any = None  # Additional arguments for comparison
    desc: str = ""     # Description for reporting
```

#### EvaluationResult
```python
class EvaluationResult(BaseModel):
    config: EvaluatorConfig  # Original configuration
    response: str | Dict     # Agent response being evaluated
    passed: bool             # Whether evaluation passed
    reason: str = ""         # Failure reason if applicable
    error: str = ""          # Error message if execution failed
```

#### FunctionResult
```python
class FunctionResult(BaseModel):
    result: Any  # The actual result data
```

### Evaluation Flow

1. **Configuration Parsing**: Parse function chain from config
2. **Function Execution**: Execute evaluation functions sequentially
3. **Comparison**: Apply comparison operator with expected value
4. **Result Generation**: Create EvaluationResult with pass/fail status

## Function Types and Decorators

### Evaluation Function Decorator

Use `@eval_func(name="function_name")` to register evaluation functions:

```python
from mcpuniverse.evaluator.functions import eval_func, FunctionResult

@eval_func(name="my_custom_func")
async def my_custom_function(x: FunctionResult, *args, **kwargs) -> FunctionResult:
    """Custom evaluation function."""
    # Process the input and return FunctionResult
    processed_data = process_data(x.result)
    return FunctionResult(result=processed_data)
```

### Comparison Function Decorator

Use `@compare_func(name="comparison_name")` to register comparison functions:

```python
from mcpuniverse.evaluator.functions import compare_func

@compare_func(name="my_custom_comparison")
async def my_custom_comparison(a: Any, b: Any, *args, **kwargs) -> tuple[bool, str]:
    """Custom comparison function."""
    # Compare values and return (success, reason)
    if custom_condition(a, b):
        return True, ""
    return False, "Custom validation failed"
```

## Implementation Steps

### Step 1: Create Module Structure

Create a new evaluator module in the appropriate domain:

```bash
mkdir mcpuniverse/evaluator/my_domain
touch mcpuniverse/evaluator/my_domain/__init__.py
touch mcpuniverse/evaluator/my_domain/functions.py
```

### Step 2: Implement Evaluation Functions

```python
# mcpuniverse/evaluator/my_domain/functions.py
"""
Evaluation functions for my custom domain
"""
import json
from typing import Any
from mcpuniverse.evaluator.functions import eval_func, compare_func, FunctionResult

@eval_func(name="extract_score")
async def extract_score(x: FunctionResult, *args, **kwargs) -> FunctionResult:
    """Extract numerical score from response."""
    if isinstance(x, FunctionResult):
        data = x.result
        if isinstance(data, dict) and 'score' in data:
            return FunctionResult(result=float(data['score']))
        elif isinstance(data, str):
            # Try to extract number from string
            import re
            match = re.search(r'\d+\.?\d*', data)
            if match:
                return FunctionResult(result=float(match.group()))
    raise ValueError("Could not extract score from input")

@eval_func(name="normalize_text")
async def normalize_text(x: FunctionResult, *args, **kwargs) -> FunctionResult:
    """Normalize text for comparison."""
    if isinstance(x, FunctionResult):
        text = str(x.result).lower().strip()
        # Remove extra whitespace
        normalized = ' '.join(text.split())
        return FunctionResult(result=normalized)
    raise ValueError("Could not normalize text")
```

### Step 3: Implement Comparison Functions

```python
@compare_func(name="score_threshold")
async def score_threshold(a: Any, b: Any, *args, **kwargs) -> tuple[bool, str]:
    """Check if score meets threshold."""
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    threshold = float(b)
    score = float(a)
    
    if score >= threshold:
        return True, ""
    return False, f"Score {score} below threshold {threshold}"

@compare_func(name="text_similarity")
async def text_similarity(a: Any, b: Any, *args, **kwargs) -> tuple[bool, str]:
    """Check text similarity using fuzzy matching."""
    from difflib import SequenceMatcher
    
    if isinstance(a, FunctionResult):
        a = a.result
    if isinstance(b, FunctionResult):
        b = b.result
    
    similarity = SequenceMatcher(None, str(a), str(b)).ratio()
    threshold = 0.8  # Default threshold
    
    if len(args) > 2 and args[2]:  # op_args provided
        threshold = float(args[2].get('threshold', 0.8))
    
    if similarity >= threshold:
        return True, ""
    return False, f"Text similarity {similarity:.2f} below threshold {threshold}"
```

### Step 4: Register Functions in Module

Update the main evaluator `__init__.py`:

```python
# mcpuniverse/evaluator/__init__.py
from .functions import *
from .my_domain.functions import *  # Add your module

__all__ = [
    "Evaluator",
    "EvaluationResult", 
    "EvaluatorConfig"
]
```

## Built-in Evaluation Functions

| Function | Purpose | Usage Example |
|----------|---------|---------------|
| `json` | Parse JSON string | `"json"` |
| `get(key)` | Extract dictionary value | `"json -> get(city)"` |
| `len` | Get array/string length | `"json -> get(items) -> len"` |
| `foreach` | Iterate over arrays | `"json -> get(routes) -> foreach -> get(name)"` |
| `raw` | Pass through data unchanged | `"raw"` |

## Built-in Comparison Functions

| Function | Purpose | Usage Example |
|----------|---------|---------------|
| `=` | Exact equality | `"op": "=", "value": "expected"` |
| `<`, `>`, `<=`, `>=` | Numerical comparison | `"op": ">", "value": 100` |
| `in` | Membership test | `"op": "in", "value": ["a", "b", "c"]` |
| `contain` | Contains test | `"op": "contain", "value": "substring"` |

## Task Configuration Example

```json
{
    "category": "ecommerce",
    "question": "Calculate the final price for a shopping cart with discount",
    "mcp_servers": [{"name": "ecommerce-api"}],
    "output_format": {
        "original_price": "<original total>",
        "discount_percentage": "<discount %age>",
        "discounted_price": "<final price>",
        "savings": "<amount saved>"
    },
    "evaluators": [
        {
            "func": "json",
            "op": "validate_discount",
            "op_args": {
                "discount_percentage": 15,
                "tolerance": 0.5
            }
        },
        {
            "func": "json -> extract_order_total",
            "op": ">",
            "value": 0
        }
    ]
}
```

This guide provides a complete framework for implementing custom evaluators in MCPUniverse. Follow these patterns and best practices to create robust, maintainable evaluation functions that accurately assess agent performance in your specific domain.