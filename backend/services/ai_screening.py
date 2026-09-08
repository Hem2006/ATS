"""
Stitch ATS — AI Screening Service
Uses OpenAI GPT-4o for semantic resume-JD matching.
"""

import os
import json
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# Load .env from the backend directory (parent of services/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

def _load_env():
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env_path)


def get_provider_chain():
    """
    Return the ordered list of provider configurations the agent will try.
    Groq → OpenAI → Gemini. Only providers with a non-empty key are included.

    Each entry: (name, client, model). safe_chat_completion iterates through
    this list on hard-auth / model-not-found errors so one dead key doesn't
    stop the whole run.
    """
    _load_env()
    import httpx
    http_client = httpx.Client(verify=False, timeout=30.0)

    providers = []
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if groq_key:
        providers.append((
            "groq",
            OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1", http_client=http_client),
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ))
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if openai_key:
        providers.append((
            "openai",
            OpenAI(api_key=openai_key, http_client=http_client),
            "gpt-4o-mini",
        ))
    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if gemini_key:
        providers.append((
            "gemini",
            OpenAI(api_key=gemini_key,
                   base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   http_client=http_client),
            "gemini-2.5-flash",
        ))
    return providers


def get_ai_client_and_model():
    """Legacy accessor kept for compatibility. Returns the first provider."""
    chain = get_provider_chain()
    if not chain:
        raise RuntimeError("No LLM provider configured. Set GROQ_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY.")
    name, client, model = chain[0]
    return client, model, name

import time

def safe_chat_completion(*args, **kwargs):
    """
    Call the LLM with (a) transient retries per provider, and (b) provider
    fallback so a dead key or removed model on the first provider automatically
    cascades to the next one.
    """
    kwargs.pop("model", None)  # provider chain sets the model
    chain = get_provider_chain()
    if not chain:
        raise RuntimeError("No LLM provider configured. Set GROQ_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY.")

    last_error: Exception = RuntimeError("no provider tried")
    for provider, client, model in chain:
        max_retries = 2
        delay = 1.0
        for attempt in range(max_retries):
            try:
                call_kwargs = dict(kwargs)
                call_kwargs["model"] = model
                return client.chat.completions.create(*args, **call_kwargs)
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_transient = any(x in err_str for x in ["429", "503", "overloaded", "rate limit", "unavailable", "resource", "timeout", "timed out"])
                is_hard_provider_error = any(x in err_str for x in [
                    "401", "403", "404", "invalid api key", "incorrect api key",
                    "model_not_found", "does not exist",
                ])
                if is_hard_provider_error:
                    print(f"[{provider}] hard error, cascading to next provider: {e}")
                    break  # try next provider
                if is_transient and attempt < max_retries - 1:
                    print(f"[{provider}] retrying in {delay}s: {e}")
                    time.sleep(delay)
                    delay *= 2
                else:
                    print(f"[{provider}] non-retryable, cascading: {e}")
                    break
    raise last_error


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


def screen_single_candidate(jd_text: str, resume_text: str, candidate_name: str) -> dict:
    """
    Screen a single candidate's resume against a job description using GPT-4o.
    Returns a dict with match_score, sub-scores, strengths, gaps, rejection_reason, etc.
    """
    prompt = f"""You are an expert HR recruiter and talent acquisition specialist. 
Analyze the following resume against the job description using SEMANTIC matching 
(not just keyword matching). Consider skills, experience level, cultural indicators, 
and transferable skills.

JOB DESCRIPTION:
{jd_text[:3000]}

CANDIDATE RESUME ({candidate_name}):
{resume_text[:3000]}

Return a JSON object with exactly these fields:
{{
    "jd_vs_cv_score": <number 0-100, score of JD matching resume/CV>,
    "jd_vs_linkedin_score": <number 0-100, or null if no LinkedIn URL or profile data is present in the resume>,
    "jd_vs_github_score": <number 0-100, or null if no GitHub URL or open-source projects are present in the resume>,
    "match_score": <number 0-100, representing the overall percentage match (average of the NON-NULL sub-scores above)>,
    "strengths": ["strength 1", "strength 2", "strength 3"],
    "gaps": ["gap 1", "gap 2"],
    "rejection_reason": "<reason string if match_score < 40, else null>",
    "seniority_fit": "<junior|mid|senior|lead>",
    "overall_summary": "<2-3 sentence summary of fit>",
    "score_justification": "<2-3 sentence explanation of why these match scores were awarded>"
}}

Be fair but thorough. A score of 70+ means shortlist-worthy. Below 40 means reject.
Return ONLY valid JSON, no markdown.
"""

    try:
        response = safe_chat_completion(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are an expert HR recruiter. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        result = json.loads(clean_json_response(response.choices[0].message.content))

        # Handle optional scores properly (they might be None/null)
        jd_vs_cv_val = result.get("jd_vs_cv_score")
        jd_vs_cv = float(jd_vs_cv_val) if jd_vs_cv_val is not None else 0.0
        
        li_val = result.get("jd_vs_linkedin_score")
        jd_vs_li = float(li_val) if li_val is not None else None
        
        gh_val = result.get("jd_vs_github_score")
        jd_vs_gh = float(gh_val) if gh_val is not None else None
        
        # Calculate/fallback overall match_score as average of non-null scores
        valid_scores = [s for s in [jd_vs_cv, jd_vs_li, jd_vs_gh] if s is not None]
        default_match = round(sum(valid_scores) / len(valid_scores)) if valid_scores else 0
        overall_val = result.get("match_score")
        overall = float(overall_val) if overall_val is not None else default_match

        return {
            "match_score": overall,
            "jd_vs_cv_score": jd_vs_cv,
            "jd_vs_linkedin_score": jd_vs_li,
            "jd_vs_github_score": jd_vs_gh,
            "strengths": json.dumps(result.get("strengths", [])),
            "gaps": json.dumps(result.get("gaps", [])),
            "rejection_reason": result.get("rejection_reason"),
            "seniority_fit": result.get("seniority_fit", "unknown"),
            "overall_summary": result.get("overall_summary", "No summary available."),
            "score_justification": result.get("score_justification", "No justification provided.")
        }
    except Exception as e:
        return {
            "match_score": 0.0,
            "jd_vs_cv_score": 0.0,
            "jd_vs_linkedin_score": None,
            "jd_vs_github_score": None,
            "strengths": json.dumps([]),
            "gaps": json.dumps([f"Error during screening: {str(e)}"]),
            "rejection_reason": f"Screening error: {str(e)}",
            "seniority_fit": "unknown",
            "overall_summary": f"Error occurred during AI screening: {str(e)}",
            "score_justification": f"Screening error occurred: {str(e)}"
        }


def suggest_interview_slots(candidate_name: str, role: str) -> list[dict]:
    """Use AI to suggest optimal interview time slots."""
    try:
        prompt = f"""Suggest 3 optimal interview time slots for a candidate named {candidate_name} 
applying for {role}. Consider typical business hours (9 AM - 5 PM).
Return a JSON array with exactly 3 objects, each having:
{{"time": "human readable time", "reason": "why this slot is good"}}
Return ONLY valid JSON array, no markdown.
"""
        response = safe_chat_completion(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are a scheduling assistant. Return only valid JSON arrays."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        result = json.loads(clean_json_response(response.choices[0].message.content))
        # Handle both direct array and wrapped object
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "slots" in result:
            return result["slots"]
        elif isinstance(result, dict) and "suggestions" in result:
            return result["suggestions"]
        else:
            # Try to find any array value in the dict
            for v in result.values():
                if isinstance(v, list):
                    return v
            return [{"time": "Tomorrow 10:00 AM", "reason": "Standard morning slot"}]
    except Exception as e:
        return [
            {"time": "Tomorrow 10:00 AM", "reason": "Standard morning slot"},
            {"time": "Tomorrow 2:00 PM", "reason": "Post-lunch energy slot"},
            {"time": "Day after 11:00 AM", "reason": "Mid-morning focus time"}
        ]


def generate_ai_email(candidate_name: str, role: str, strengths: list, gaps: list, summary: str, email_type: str, details: dict) -> dict:
    """Use GPT-4o to generate a highly personalized, friendly email draft for the candidate."""
    details_str = json.dumps(details) if details else ""
    
    if email_type == "invitation":
        prompt = f"""You are a professional corporate recruiter. Write a friendly, warm, and highly personalized email inviting {candidate_name} to an interview for the {role} position.
        
        CANDIDATE DETAILS:
        - Strengths: {strengths}
        - Gaps: {gaps}
        - Overall Fit Summary: {summary}
        - Interview Details: {details_str}
        
        Write a standard subject line and body. 
        In the body:
        - Thank them for applying.
        - Mention 1-2 specific strengths from their CV (derived from the CANDIDATE DETAILS) that impressed our team.
        - Give the interview date, time, and interviewer name if available in the Interview Details.
        - Sound welcoming and enthusiastic.
        
        Return a JSON object with exactly these fields:
        {{
            "subject": "<Subject line>",
            "body": "<Email body with formatting like newlines. Use placeholders like [Interviewer Name] if missing from details, but do not use brackets if details are provided.>"
        }}
        Return ONLY valid JSON.
        """
    else: # offer_letter
        prompt = f"""You are a head of talent acquisition. Write a warm, formal, and exciting job offer letter to {candidate_name} for the {role} position.
        
        CANDIDATE DETAILS:
        - Strengths: {strengths}
        - Overall Fit Summary: {summary}
        - Offer Details: {details_str}
        
        Write a subject line and the offer letter body.
        In the body:
        - Formally offer them the position.
        - Express how excited the team is to have them join, highlighting how their specific strengths fit the role.
        - Explain that we will begin provisioning their access credentials and hardware (e.g. MacBook) shortly (referencing our onboarding automation).
        
        Return a JSON object with exactly these fields:
        {{
            "subject": "<Subject line>",
            "body": "<Job offer letter body with formatting like newlines.>"
        }}
        Return ONLY valid JSON.
        """

    try:
        response = safe_chat_completion(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are a professional recruitment assistant. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        result = json.loads(clean_json_response(response.choices[0].message.content))
        return {
            "subject": result.get("subject", "Interview Invitation: Stitch ATS"),
            "body": result.get("body", f"Dear {candidate_name},\n\nWe would love to invite you to an interview...")
        }
    except Exception as e:
        return {
            "subject": f"Interview Invitation - {role}",
            "body": f"Dear {candidate_name},\n\nWe are pleased to invite you to discuss the {role} position. Our team will contact you shortly to coordinate time slots."
        }


def generate_candidate_rubric(candidate_name: str, role: str, resume_text: str, jd_text: str) -> dict:
    """
    Generate a 5-question customized technical interview rubric for a candidate
    based on their resume and the job description using LLM.
    """
    prompt = f"""You are a senior technical interviewer and engineering manager.
Create a structured technical interview rubric consisting of exactly 5 custom questions 
tailored specifically to the candidate's actual experience on their resume and the target Job Description.

JOB DESCRIPTION / TARGET ROLE:
Role: {role}
JD Detail: {jd_text[:2000] if jd_text else "No specific JD detail available."}

CANDIDATE RESUME ({candidate_name}):
{resume_text[:2000] if resume_text else "No resume text available. Generate standard questions for this role."}

For each of the 5 questions:
1. Formulate a clear, specific question based on their technologies or project experiences (if resume is available) or core expectations for the role.
2. Provide the expected answer.
3. List the skills tested.
4. Define a simple grading rubric for the response:
   - What a Pass response looks like.
   - What a Good response looks like.
   - What an Excellent response looks like.

Return a JSON object with exactly this format:
{{
    "candidate_name": "{candidate_name}",
    "role": "{role}",
    "rubrics": [
        {{
            "question": "<Specific interview question>",
            "expected_answer": "<The ideal expected technical answer>",
            "skills_tested": "<Comma-separated skills tested, e.g. React, State Management>",
            "grading_rubric": {{
                "pass": "<Short description of a minimum passing response>",
                "good": "<Short description of a good response>",
                "excellent": "<Short description of an excellent, highly-detailed response>"
            }}
        }},
        ...
    ]
}}

Return ONLY valid JSON. Do not wrap in backticks or include other text.
"""
    try:
        response = safe_chat_completion(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are a senior technical interviewer. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            response_format={"type": "json_object"}
        )
        content = clean_json_response(response.choices[0].message.content)
        result = json.loads(content)
        return result
    except Exception as e:
        # Fallback rubric structure
        return {
            "candidate_name": candidate_name,
            "role": role,
            "rubrics": [
                {
                    "question": f"Explain your experience working with {role} technologies and libraries.",
                    "expected_answer": "Candidate should detail practical experience, naming specific projects, frameworks, and tools used.",
                    "skills_tested": "General Technical Experience, Architecture",
                    "grading_rubric": {
                        "pass": "Mentions basic concepts and standard library usage.",
                        "good": "Explains system design, trade-offs, and state management details.",
                        "excellent": "Demonstrates deep mastery of performance optimization, scaling, and custom integrations."
                    }
                },
                {
                    "question": "Can you describe a challenging technical issue you solved in a past project?",
                    "expected_answer": "Candidate should outline the problem, their debugging process, their solution, and what they learned.",
                    "skills_tested": "Problem Solving, Debugging",
                    "grading_rubric": {
                        "pass": "Resolves a simple syntax or logic bug.",
                        "good": "Fixes a complex configuration or concurrency issue with clear steps.",
                        "excellent": "Optimizes a database query or network lag, providing solid performance metrics before/after."
                    }
                },
                {
                    "question": "How do you ensure code quality, testability, and adherence to clean coding principles in your team?",
                    "expected_answer": "Candidate should discuss unit testing, code reviews, linting, CI/CD, and DRY/SOLID patterns.",
                    "skills_tested": "Software Engineering Best Practices, Testing",
                    "grading_rubric": {
                        "pass": "Writes simple unit tests and follows style guides.",
                        "good": "Configures automatic linting/CI pipelines and conducts thorough pull-request reviews.",
                        "excellent": "Designs modular, decoupled interfaces following SOLID principles and maintains high test coverage."
                    }
                },
                {
                    "question": "What is your approach to handling asynchronous operations, state changes, or API integration issues?",
                    "expected_answer": "Candidate should detail error handling, caching, state propagation, and asynchronous control flows.",
                    "skills_tested": "Async Programming, API Integration",
                    "grading_rubric": {
                        "pass": "Uses basic try/catch or async/await syntax.",
                        "good": "Handles rate limiting, loading states, and updates state libraries cleanly.",
                        "excellent": "Implements debouncing, optimistic updates, and offline caching patterns."
                    }
                },
                {
                    "question": "Describe a scenario where you had to collaborate with stakeholders on an ambiguous product requirement.",
                    "expected_answer": "Candidate should explain how they clarify constraints, communicate technical limits, and iterate on specs.",
                    "skills_tested": "Communication, Technical Alignment",
                    "grading_rubric": {
                        "pass": "Asks questions and implements the best guess.",
                        "good": "Drafts basic design docs or mockups to align with the product owner before building.",
                        "excellent": "Proposes iterative deliverables (MVP), tracks edge cases, and guides product decisions using tech metrics."
                    }
                }
            ]
        }

