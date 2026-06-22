"""
HLE / deep-research LLM-as-a-judge evaluator (structured parse + OpenAI).

Registered as ``deepresearch.hle_llm_as_a_judge`` for task JSON ``evaluators[].op``.
"""
# pylint: disable=broad-exception-caught,unused-argument
import os
from typing import Any, Literal

from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel

from mcpuniverse.evaluator.functions import compare_func

load_dotenv()


##################################################################################
# Eval Function for HLE/Browse-Comp Official Implementation
# https://arxiv.org/html/2501.14249v1
##################################################################################


def deepresearch__get_hle_judge_prompt(
    question: str,
    response: str,
    correct_answer: str,
) -> str:
    """
    Get a prompt for a judge.
    """
    return (
        "Judge whether the following [response] to [question] is correct or not "
        "based on the precise and unambiguous [correct_answer] below.\n\n"
        f"[question]: {question}\n\n"
        f"[response]: {response}\n\n"
        "Your judgement must be in the format and criteria specified below:\n\n"
        "extracted_final_answer: The final exact answer extracted from the "
        "[response]. Put the extracted answer as 'None' if there is no exact, "
        "final answer to extract from the response.\n\n"
        f"[correct_answer]: {correct_answer}\n\n"
        "reasoning: Explain why the extracted_final_answer is correct or incorrect "
        "based on [correct_answer], focusing only on if there are meaningful "
        "differences between [correct_answer] and the extracted_final_answer. "
        "Do not comment on any background to the problem, do not attempt to solve "
        "the problem, do not argue for any answer different than [correct_answer], "
        "focus only on whether the answers match.\n\n"
        "correct: Answer 'yes' if extracted_final_answer matches the [correct_answer] "
        "given above, or is within a small margin of error for numerical problems. "
        "Answer 'no' otherwise, i.e. if there if there is any inconsistency, "
        "ambiguity, non-equivalency, or if the extracted answer is incorrect.\n\n"
        "confidence: The extracted confidence score between 0|%| and 100|%| from "
        "[response]. Put 100 if there is no confidence score available."
    )


class HLEExtractedAnswer(BaseModel):
    """Structured answer extracted by the HLE judge."""

    extracted_final_answer: str
    reasoning: str
    correct: Literal["yes", "no"]
    confidence: int
    strict: Literal[True] = True  # 100% reliability


def deepresearch__call_gpt_hle(
    prompt: str,
    model="o3-mini-2025-01-31",
    **kwargs,
) -> str:
    """
    Call GPT to get a response to a prompt.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = None
    attempt = 5
    while attempt > 0:
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                max_completion_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                response_format=HLEExtractedAnswer,
            )
            return response.choices[0].message.parsed
        except Exception as e:
            attempt -= 1
            print(f"Error: {e}")
    return response


@compare_func(name="deepresearch.hle_llm_as_a_judge")
async def deepresearch__hle_llm_as_a_judge(
    llm_response: Any, *args, **kwargs
) -> tuple[bool, str]:
    """Equal"""
    _, values = args
    question = values["question"]
    correct_answer = values["correct_answer"]
    error_message = ""
    max_tries = 3
    for _ in range(max_tries):
        try:
            response = llm_response.result
            prompt = deepresearch__get_hle_judge_prompt(
                question, response, correct_answer
            )
            response = deepresearch__call_gpt_hle(prompt, **kwargs)
            if response.extracted_final_answer is None:
                return (
                    False,
                    f"output is not equal to ground-truth, extracted_final_answer is None, {prompt}",
                )
            if response.correct == "yes":
                return True, ""
            if response.correct == "no":
                return (
                    False,
                    f"output is not equal to ground-truth, correct is no, {prompt}",
                )
            return False, f"HLE LLM evaluation failed: {response}"
        except Exception as e:
            error_message += str(e) + "\n" + str(llm_response) + "\n" + "-" * 33 + "\n"
    return False, "ERROR: " + error_message
