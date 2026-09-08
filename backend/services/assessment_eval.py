"""
Stitch ATS — AI Assessment Evaluation Service
Handles generating custom 10-question tests from JDs and grading candidate answers using OpenAI GPT-4o.
"""

import os
import json
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# Load .env
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Delegate to the shared provider chain in ai_screening so both routers
# use the same fallback logic.
from .ai_screening import safe_chat_completion, get_ai_client_and_model  # noqa: F401
import time  # noqa: F401  (kept for module-level API compatibility)


def clean_json_response(content: str) -> str:
    content = content.strip()
    
    first_brace = content.find('{')
    first_bracket = content.find('[')
    
    if first_brace == -1 and first_bracket == -1:
        return content
    elif first_brace == -1:
        start_idx = first_bracket
    elif first_bracket == -1:
        start_idx = first_brace
    else:
        start_idx = min(first_brace, first_bracket)
        
    last_brace = content.rfind('}')
    last_bracket = content.rfind(']')
    
    if last_brace == -1 and last_bracket == -1:
        return content
    elif last_brace == -1:
        end_idx = last_bracket
    elif last_bracket == -1:
        end_idx = last_brace
    else:
        end_idx = max(last_brace, last_bracket)
        
    if start_idx < end_idx:
        return content[start_idx:end_idx+1].strip()
    return content


def generate_screening_questions(job_title: str, jd_text: str) -> list[str]:
    """
    Generate exactly 10 screening questions tailored for a job description.
    """
    prompt = f"""You are an expert HR recruiter and talent acquisition specialist.
Generate exactly 10 screening questions for the position of "{job_title}" based on the job description below.
The questions should evaluate technical capability, relevant experience, problem-solving, and culture fit.
The questions should be direct and clear, suitable for a candidate to type a short text answer (2-4 sentences).

JOB DESCRIPTION:
{jd_text[:3000]}

Return a JSON object with exactly this format:
{{
    "questions": [
        "Question 1 description",
        "Question 2 description",
        ...
        "Question 10 description"
    ]
}}
Return ONLY valid JSON. No markdown wrappers.
"""
    try:
        response = safe_chat_completion(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are a professional HR assistant. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            response_format={"type": "json_object"}
        )

        result = json.loads(clean_json_response(response.choices[0].message.content))
        questions = result.get("questions", [])
        
        # Ensure we have exactly 10 questions or back fill
        if len(questions) < 10:
            while len(questions) < 10:
                questions.append(f"Tell us about your experience relevant to {job_title}.")
        return questions[:10]
    except Exception as e:
        # Return fallback questions
        return [
            f"Explain your experience working as a {job_title}.",
            "Describe a challenging technical problem you solved recently and how you approached it.",
            "What programming languages/tools do you feel most comfortable with, and why?",
            "How do you keep your skills up to date with changing industry trends?",
            "Describe your ideal work environment and team collaboration style.",
            "What is your approach to handling tight deadlines or shifting project requirements?",
            "Why are you interested in joining our company for this specific position?",
            "Give an example of a time you had to learn a new tool or framework quickly. How did you do it?",
            "How do you ensure code quality and test your implementations?",
            "What are your salary expectations and availability for interviews?"
        ]


def grade_assessment(job_title: str, jd_text: str, questions: list[str], answers: list[str]) -> dict:
    """
    Grade candidate answers to the screening questions using GPT-4o.
    Returns score, status (passed/failed), and feedback per question.
    """
    # Build list of Q&A for the prompt
    qa_list = []
    for i, q in enumerate(questions):
        ans = answers[i] if i < len(answers) else "[No Answer Provided]"
        qa_list.append(f"Question {i+1}: {q}\nCandidate Answer: {ans}\n")
    
    qa_block = "\n".join(qa_list)

    prompt = f"""You are an expert technical evaluator. Grade the candidate's answers to the 10 screening questions for the position of "{job_title}".
Compare their answers against standard industry expectations and the specific job description criteria.

JOB DESCRIPTION:
{jd_text[:2000]}

CANDIDATE RESPONSES:
{qa_block}

Grade each response out of 10 points. Calculate the final score out of 100.
CRITICAL INSTRUCTION: If an answer is blank, gibberish, completely irrelevant, or ridiculously short (e.g., 's s s', 'none', 'idk', random characters), you MUST give it a score of exactly 0 points. Do not award pity points or partial credit for nonsense answers.

If the final score is 60 or higher, the candidate passes ("status": "passed"). If the score is below 60, they fail ("status": "failed").

Return a JSON object with exactly this format:
{{
    "score": <number 0-100>,
    "status": "<passed|failed>",
    "overall_feedback": "<brief 2-3 sentence summary of candidate performance>",
    "question_feedback": [
        {{
            "question": "question text",
            "answer": "candidate answer text",
            "score": <number 0-10>,
            "feedback": "<brief feedback on this specific response>"
        }},
        ...
    ]
}}
Return ONLY valid JSON.
"""
    try:
        response = safe_chat_completion(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are a professional hiring evaluator. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        result = json.loads(clean_json_response(response.choices[0].message.content))
        
        # Validate structure
        score = float(result.get("score", 0.0))
        status = result.get("status", "failed")
        # Ensure status is passed or failed based on score
        if score >= 60.0:
            status = "passed"
        else:
            status = "failed"

        return {
            "score": score,
            "status": status,
            "overall_feedback": result.get("overall_feedback", "Grading complete."),
            "question_feedback": result.get("question_feedback", [])
        }
    except Exception as e:
        return {
            "score": 0.0,
            "status": "failed",
            "overall_feedback": f"Error during automated grading: {str(e)}",
            "question_feedback": [{"question": q, "answer": answers[i] if i < len(answers) else "", "score": 0, "feedback": f"Grading error: {str(e)}"} for i, q in enumerate(questions)]
        }


def generate_candidate_assessment_questions(job_title: str, jd_text: str, candidate_name: str, resume_text: str) -> list[str]:
    """
    Generate exactly 10 custom screening questions for a candidate based on their CV 
    (years of experience, listed skills, background) and aligned with the JD requirements.
    """
    prompt = f"""You are an expert HR recruiter and technical interviewer.
Generate exactly 10 custom screening questions for a candidate named "{candidate_name}" who is applying for the position of "{job_title}".
The questions must be highly tailored to the candidate's unique skills and experience level extracted from their resume, and align directly with the Job Description (JD) requirements.

JOB DESCRIPTION:
{jd_text[:2000]}

CANDIDATE RESUME:
{resume_text[:2000]}

Instructions:
1. Examine the candidate's years of experience and level of seniority (e.g. junior, mid, senior, lead). Adjust the complexity of the questions accordingly.
2. Target the specific programming languages, tools, and technical concepts listed in their resume that overlap with the JD requirements.
3. Include 2-3 questions focusing on their past projects or experience described in their resume, asking how they would apply them to the requirements of the job.
4. The questions should be direct and clear, suitable for a candidate to type a short text answer (2-4 sentences).

Return a JSON object with exactly this format:
{{
    "questions": [
        "Question 1",
        "Question 2",
        ...
        "Question 10"
    ]
}}
Return ONLY valid JSON.
"""
    try:
        response = safe_chat_completion(
            messages=[
                {"role": "system", "content": "You are a professional technical interviewer. Return only valid JSON objects."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            response_format={"type": "json_object"}
        )
        result = json.loads(clean_json_response(response.choices[0].message.content.strip()))
        questions = result.get("questions", [])
        if len(questions) < 10:
            while len(questions) < 10:
                questions.append(f"Describe your experience with key technologies in this role.")
        return questions[:10]
    except Exception as e:
        print(f"[GENERATE CUSTOM QUESTIONS ERROR] {e}")
        # Return fallback
        return generate_screening_questions(job_title, jd_text)

