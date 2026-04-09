from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from brain import Brain
from scorer import ResumeScorer
from browser import BrowserController
import asyncio

class DiscoveryState(TypedDict):
    platforms: List[str]
    jobs_to_process: List[Any] # Handles to job cards or URLs
    scored_jobs: List[Dict[str, Any]]
    current_job: Optional[Dict[str, Any]]
    resume_path: str
    threshold: int
    logs: List[str]
    # HITL fields
    current_question: Optional[str]
    user_answer: Optional[str]

class DiscoveryAgentGraph:
    def __init__(self, brain: Brain, scorer: ResumeScorer, browser: BrowserController):
        self.brain = brain
        self.scorer = scorer
        self.browser = browser
        self.workflow = StateGraph(DiscoveryState)
        self._build_graph()

    def _build_graph(self):
        self.workflow.add_node("discover_jobs", self.discover_jobs_node)
        self.workflow.add_node("score_single_job", self.score_single_job_node)
        self.workflow.add_node("apply_to_job", self.apply_to_job_node)
        self.workflow.add_node("handle_form", self.handle_form_node)
        
        self.workflow.set_entry_point("discover_jobs")
        
        self.workflow.add_conditional_edges(
            "discover_jobs",
            self.check_jobs_remaining,
            {
                "continue": "score_single_job",
                "end": END
            }
        )
        
        self.workflow.add_conditional_edges(
            "score_single_job",
            self.check_apply_condition,
            {
                "apply": "apply_to_job",
                "next": "score_single_job",
                "end": END
            }
        )

        self.workflow.add_edge("apply_to_job", "handle_form")
        
        self.workflow.add_conditional_edges(
            "handle_form",
            self.check_form_condition,
            {
                "more": "handle_form",
                "next_job": "score_single_job",
                "end": END
            }
        )
        
        self.app = self.workflow.compile()

    def check_jobs_remaining(self, state: DiscoveryState) -> str:
        if state["jobs_to_process"]:
            return "continue"
        return "end"

    def check_apply_condition(self, state: DiscoveryState) -> str:
        if state.get("current_job"):
            return "apply"
        if state["jobs_to_process"]:
            return "next"
        return "end"

    def check_form_condition(self, state: DiscoveryState) -> str:
        if state.get("current_question"):
            return "more"
        if state["jobs_to_process"]:
            return "next_job"
        return "end"

    async def discover_jobs_node(self, state: DiscoveryState) -> DiscoveryState:
        print(f"[NODE] Entering discover_jobs_node")
        all_jobs_to_process = []
        for platform in state["platforms"]:
            state["logs"].append(f"🔍 Searching **{platform}**...")
            if platform.lower() == "linkedin":
                urls = await self.browser.get_linkedin_job_cards()
                all_jobs_to_process.extend([{"url": u, "platform": "LinkedIn"} for u in urls])
            elif platform.lower() == "handshake":
                urls = await self.browser.scrape_handshake_jobs()
                all_jobs_to_process.extend([{"url": u, "platform": "Handshake"} for u in urls])
        
        # ONLY PROCESS 1 JOB total as requested by user
        if all_jobs_to_process:
            all_jobs_to_process = all_jobs_to_process[:1]
            
        state["jobs_to_process"] = all_jobs_to_process
        state["logs"].append(f"✅ Found **{len(all_jobs_to_process)}** job to process.")
        print(f"[NODE] Discovered {len(all_jobs_to_process)} job(s) total.")
        return state

    async def score_single_job_node(self, state: DiscoveryState) -> DiscoveryState:
        print(f"[NODE] Entering score_single_job_node. Remaining: {len(state['jobs_to_process'])}")
        if not state["jobs_to_process"]: 
            state["logs"].append("🏁 All jobs processed.")
            return state
        
        job_info = state["jobs_to_process"].pop(0)
        url = job_info["url"]
        platform = job_info["platform"]
        
        # We don't have the title yet, so we just say reading URL
        state["logs"].append(f"📖 Reading job at **{url[:50]}...**")
        print(f"[DEBUG] Processing job: {url}")
        
        # Scrape details for THIS job only
        try:
            if platform == "LinkedIn":
                job = await self.browser.scrape_job_card_details(url)
            else:
                job = await self.browser.scrape_handshake_job_details(url)
        except Exception as e:
            print(f"[ERROR] Node score_single_job failed on {url}: {e}")
            state["logs"].append(f"⚠️ Error reading job: {str(e)}")
            return state
            
        if not job:
            state["logs"].append(f"⚠️ Could not read details, skipping to next.")
            return state

        state["logs"].append(f"⚖️ Scoring **{job['title']}** - **{job.get('company', 'N/A')}**")
        result = await self.scorer.score_resume(state["resume_path"], job.get("description", ""))
        job["score"] = result.get("score", 0)
        job["reasoning"] = result.get("reasoning", "N/A")
        state["scored_jobs"].append(job)
        
        reasoning = job.get("reasoning", "N/A").split('.')[:2]
        reason_text = ".".join(reasoning).strip() + "."
        
        # Score message
        threshold = state.get("threshold", 80)
        if job["score"] >= threshold:
            state["logs"].append(f"🎯 Score of **{job['score']}** > {threshold} for **{job['title']}**")
            state["current_job"] = job
        else:
            state["logs"].append(f"⏩ Score of **{job['score']}** < {threshold} for **{job['title']}**. Skipping.")
            state["current_job"] = None

        return state

    async def apply_to_job_node(self, state: DiscoveryState) -> DiscoveryState:
        job = state["current_job"]
        print(f"[NODE] Entering apply_to_job_node for {job['title']}")
        state["logs"].append(f"🚀 Applying to **{job['title']}**...")
        await self.browser.navigate(job["url"])
        
        apply_type = await self.browser.click_apply()
        print(f"[DEBUG] Apply clicked. Type: {apply_type}")
        if apply_type == "None":
            state["logs"].append(f"❌ Could not find apply button for **{job['title']}**.")
            state["current_job"] = None
        elif apply_type == "External Apply":
            state["logs"].append(f"🔗 External site detected for **{job['title']}**. Attempting to fill...")
        else:
            state["logs"].append(f"📝 LinkedIn Easy Apply started for **{job['title']}**.")
            
        return state

    async def handle_form_node(self, state: DiscoveryState) -> DiscoveryState:
        print(f"[NODE] Entering handle_form_node. Current URL: {self.browser.page.url}")
        state["logs"].append("🛠️ Detecting form fields/questions...")
        questions = await self.browser.get_form_questions()
        if not questions:
            # Try to click next/submit with LLM assistance
            btn_text = await self.browser.submit_application_step(llm=self.scorer.llm)
            if btn_text:
                state["logs"].append(f"Clicked: {btn_text}")
                # Check for more questions on the next page
                return await self.handle_form_node(state)
            else:
                # If we are on an external site, give the user a chance to help instead of just finishing
                if "linkedin.com" not in self.browser.page.url:
                    state["logs"].append("🤔 I'm having trouble finding the 'Next' or 'Apply' button on this external page.")
                    state["current_question"] = "I can't see how to move forward on this page. Can you point me to the right button or click it for me in the browser?"
                    return state
                    
                state["logs"].append("✅ Application cycle finished.")
                await self.browser.finish_application()
                state["current_question"] = None
                return state

        # We have questions. Try to use Brain first.
        for q in questions:
            answer = self.brain.get_learned_answer(q["text"])
            if answer:
                try:
                    state["logs"].append(f"Auto-filling: '{q['text']}' with '{answer}'")
                    if q["type"] == "file":
                        state["logs"].append(f"📎 Skipping file upload for '{q['text']}'. Please handle manually if needed.")
                        continue
                    elif q["type"] in ["checkbox", "radio"]:
                        if "yes" in answer.lower() or "true" in answer.lower():
                            await q["element"].click()
                    else:
                        await q["element"].fill(answer)
                except Exception as e:
                    print(f"[ERROR] Failed to fill field '{q['text']}': {e}")
                    state["logs"].append(f"⚠️ Could not auto-fill '{q['text']}', skipping...")
                    continue
            else:
                # BREAKPOINT: Found a new question
                state["current_question"] = q["text"]
                # In a real LangGraph setup, we'd use interrupt() here
                # But for this implementation, we'll signal the UI
                state["logs"].append(f"❓ Need help: '{q['text']}'")
                # For this specific app, we pause and wait for the UI to provide answers.
                # The app.py will detect state['current_question'] and ask the user.
                return state

        state["current_question"] = None
        return state
