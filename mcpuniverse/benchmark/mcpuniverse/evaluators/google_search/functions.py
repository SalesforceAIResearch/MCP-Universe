"""
Evaluation functions for Yahoo finance tasks
"""
# pylint: disable=broad-exception-caught,unused-argument
from typing import Any
from openai import OpenAI
from dotenv import load_dotenv
from mcpuniverse.evaluator.functions import compare_func
from mcpuniverse.common.context import Context

load_dotenv()


##################################################################################
# Utils Function for Google Search
##################################################################################

def google_search__get_judge_prompt(
        question: str,
        response: str,
        correct_answer: str
) -> str:
    """
    Get a prompt for a judge.
    """
    return f"""
Judge whether the following [response] to [question] is correct or not based on the precise and unambiguous [correct_answer] below.

[question]: {question}

[response]: {response}

Your judgement must be in the format and criteria specified below:

extracted_final_answer: The final exact answer extracted from the [response]. Put the extracted answer as 'None' if there is no exact, final answer to extract from the response.

[correct_answer]: {correct_answer}

reasoning: Explain why the extracted_final_answer is correct or incorrect based on [correct_answer], focusing only on if there are meaningful differences between [correct_answer] and the extracted_final_answer. Do not comment on any background to the problem, do not attempt to solve the problem, do not argue for any answer different than [correct_answer], focus only on whether the answers match.

correct: Answer 'yes' if extracted_final_answer matches the [correct_answer] given above, or is within a small margin of error for numerical problems. Answer 'no' otherwise, i.e. if there if there is any inconsistency, ambiguity, non-equivalency, or if the extracted answer is incorrect.
"""


def google_search__call_gpt(
        prompt: str,
        model: str = "gpt-4.1",
        temperature: float = 0.0,
        **kwargs
) -> str:
    """
    Call GPT to get a response to a prompt.
    """
    context: Context = kwargs.get("context", Context())
    client = OpenAI(api_key=context.get_env("OPENAI_API_KEY"))
    response = None
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
    return response


##################################################################################
# Eval Function for Google-Maps
##################################################################################


@compare_func(name="google_search.llm_as_a_judge")
async def google_search__llm_as_a_judge(llm_response: Any, *args, **kwargs) -> (bool, str):
    """Equal"""
    _, values = args
    question = values['question']
    correct_answer = values['correct_answer']
    error_message = ""
    max_tries = 3
    for _ in range(max_tries):
        try:
            response = llm_response if isinstance(llm_response, str) else llm_response.result
            prompt = google_search__get_judge_prompt(question, response, correct_answer)
            response = google_search__call_gpt(prompt, **kwargs)
            if response is None:
                return False, "output is not equal to ground-truth"
            judge = response.split("correct:")[1].strip()
            if "yes" in judge:
                return True, ""
            return False, "output is not equal to ground-truth"
        except Exception as e:
            error_message += str(e) + "\n" + str(llm_response) + "\n" + "-" * 33 + "\n"
    return False, "ERROR: " + error_message
