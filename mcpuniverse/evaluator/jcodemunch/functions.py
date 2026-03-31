"""
Evaluation functions for jcodemunch-mcp code intelligence tasks.

jcodemunch-mcp is a code intelligence MCP server that provides symbol search,
file outlines, cross-repo dependency mapping, and targeted code retrieval with
dramatically reduced token usage compared to naive file reading.
"""
# pylint: disable=broad-exception-caught,unused-argument
from typing import Any
from openai import OpenAI
from dotenv import load_dotenv
from mcpuniverse.evaluator.functions import compare_func
from mcpuniverse.common.context import Context

load_dotenv()


##################################################################################
# Utils
##################################################################################

def jcodemunch__get_judge_prompt(question: str, response: str, correct_answer: str) -> str:
    return f"""
Judge whether the following [response] to [question] is correct or not based on the [correct_answer].

[question]: {question}

[response]: {response}

Your judgement must be in the format and criteria specified below:

extracted_final_answer: The final exact answer extracted from the [response]. Put 'None' if there is no extractable answer.

[correct_answer]: {correct_answer}

reasoning: Explain why the extracted_final_answer is correct or incorrect based on [correct_answer]. Focus only on whether the answers match meaningfully — ignore formatting differences, extra context, or minor phrasing variations.

correct: Answer 'yes' if extracted_final_answer meaningfully matches [correct_answer]. Answer 'no' otherwise.
"""


def jcodemunch__call_gpt(
        prompt: str,
        model: str = "gpt-4.1",
        temperature: float = 0.0,
        **kwargs
) -> str:
    context: Context = kwargs.get("context", Context())
    client = OpenAI(api_key=context.get_env("OPENAI_API_KEY"))
    attempt = 5
    while attempt > 0:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            attempt -= 1
            print(f"Error: {e}")
    return None


##################################################################################
# Comparison functions
##################################################################################

@compare_func(name="jcodemunch.llm_as_a_judge")
async def jcodemunch__llm_as_a_judge(llm_response: Any, *args, **kwargs) -> (bool, str):
    """
    LLM-as-a-judge evaluator for jcodemunch code intelligence tasks.
    Checks whether the agent's response correctly answers the question
    given a known-correct answer about the indexed codebase.
    """
    _, values = args
    question = values["question"]
    correct_answer = values["correct_answer"]
    error_message = ""
    for _ in range(3):
        try:
            response = llm_response if isinstance(llm_response, str) else llm_response.result
            prompt = jcodemunch__get_judge_prompt(question, response, correct_answer)
            judge_response = jcodemunch__call_gpt(prompt, **kwargs)
            if judge_response is None:
                return False, "LLM judge returned no response"
            verdict = judge_response.split("correct:")[1].strip()
            if "yes" in verdict:
                return True, ""
            return False, "output does not match expected answer"
        except Exception as e:
            error_message += str(e) + "\n"
    return False, "ERROR: " + error_message


@compare_func(name="jcodemunch.check_fields_present")
async def jcodemunch__check_fields_present(llm_response: Any, *args, **kwargs) -> (bool, str):
    """
    Checks that the agent's JSON response contains all required fields.
    op_args should be a list of required field names.
    """
    import json as json_mod
    _, required_fields = args
    try:
        raw = llm_response if isinstance(llm_response, str) else llm_response.result
        if isinstance(raw, str):
            raw = raw.strip().strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
            data = json_mod.loads(raw)
        else:
            data = raw
        missing = [f for f in required_fields if f not in data]
        if missing:
            return False, f"Missing required fields: {missing}"
        return True, ""
    except Exception as e:
        return False, f"Could not parse response as JSON: {e}"
