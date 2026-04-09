import PyPDF2
import re
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from typing import Dict, Any

class ResumeScorer:
    def __init__(self, model_name: str = "gemma4:e4b"):
        self.llm = ChatOllama(model=model_name)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a hiring manager "Gatekeeper" agent. 
            Your task is to compare a candidate's resume with a Job Description.
            
            HARD EXCLUSION CRITERIA:
            If the job description has a mandatory requirement that is clearly NOT present on the resume, you MUST score the job as 0.
            Examples of Hard Exclusions:
            - "Military Veteran only" or "Military background required" (Candidate is a student, not a veteran).
            - "Active Top Secret Security Clearance required" (Candidate does not list a clearance).
            - "U.S. Citizenship REQUIRED" (If the resume indicates international status, but here assume if missing it is a risk).
            
            SCORING:
            - Provide a score from 0 to 100.
            - If a Hard Exclusion is hit, Score = 0.
            - If Score < 100, you MUST explicitly state what is MISSING or why the candidate isn't a perfect 10/10 (e.g., missing specific years of experience, missing a specific framework, or seniority mismatch).
            
            Format your output as JSON with keys: "score" (int) and "reasoning" (str).
            The "reasoning" should be 1-2 sentences max: [Top Strength]. [Specific Gap/Missing Skill]."""),
            ("user", "REUME:\n{resume_text}\n\nJOB DESCRIPTION:\n{job_description}")
        ])

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        text = ""
        try:
            with open(pdf_path, "rb") as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    text += page.extract_text()
        except Exception as e:
            print(f"Error reading PDF: {e}")
        return text

    async def score_resume(self, resume_path: str, job_description: str) -> Dict[str, Any]:
        resume_text = self.extract_text_from_pdf(resume_path)
        
        if not resume_text or len(resume_text) < 100:
            return {"score": 0, "reasoning": "Failed to extract text from resume PDF."}
            
        # Clean up the resume text (remove excessive spacing observed in previous run)
        resume_text = re.sub(r'\s+', ' ', resume_text).strip()

        chain = self.prompt | self.llm
        # Add a very strict suffix to the prompt
        response = await chain.ainvoke({
            "resume_text": resume_text,
            "job_description": job_description + "\n\nCRITICAL: YOU MUST RESPOND WITH ONLY A JSON OBJECT. NO OTHER TEXT. NO EXPLANATIONS. ONLY JSON."
        })
        
        content = response.content.strip()
        try:
            import json
            # Improved JSON extraction
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1:
                json_str = content[start:end+1]
                return json.loads(json_str)
            
            # Fallback: Try to find a number if the LLM provided a rating/score in text
            score_match = re.search(r'score["\s:]+(\d+)', content, re.IGNORECASE)
            if score_match:
                return {"score": int(score_match.group(1)), "reasoning": "Extracted score via regex fallback."}
                
            # Second fallback: If there's a table with star ratings, guess a score
            stars = len(re.findall(r'⭐', content))
            if stars > 0:
                # Assuming top rating is ~20 stars in a table (4 categories * 5 stars)
                estimated_score = min(100, (stars / 20) * 100)
                return {"score": int(estimated_score), "reasoning": "Estimated score from star ratings."}

            print(f"DEBUG: LLM failed JSON and fallback: {content[:200]}...")
            return {"score": 0, "reasoning": f"Format error. First 50 chars: {content[:50]}"}
        except Exception as e:
            print(f"DEBUG: Parse error: {e}. Raw content: {content}")
            return {"score": 0, "reasoning": f"Error parsing response: {str(e)}"}

if __name__ == "__main__":
    # Test (requires Ollama running with gemma4)
    import asyncio
    async def test():
        scorer = ResumeScorer()
        # Assuming the user's resume is in the directory
        res = await scorer.score_resume("2-6-2026%20-%20Cole_Determan_Resume.pdf.pdf", "Senior Python Developer with LangGraph experience.")
        print(res)
    # asyncio.run(test())
