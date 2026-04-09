from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from brain import Brain
from scorer import ResumeScorer
from browser import BrowserController
import asyncio

class DiscoveryState(TypedDict):
    platforms: List[str]
    jobs_to_score: List[Dict[str, Any]]
    scored_jobs: List[Dict[str, Any]]
    current_job: Optional[Dict[str, Any]]
    resume_path: str
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
        if state["jobs_to_score"]:
            return "continue"
        return "end"

    def check_apply_condition(self, state: DiscoveryState) -> str:
        last_job = state["scored_jobs"][-1] if state["scored_jobs"] else None
        if last_job and last_job["score"] >= 90: # Only auto-apply to very high scores
            state["current_job"] = last_job
            return "apply"
        if state["jobs_to_score"]:
            return "next"
        return "end"

    def check_form_condition(self, state: DiscoveryState) -> str:
        if state.get("current_question"):
            return "more"
        if state["jobs_to_score"]:
            return "next_job"
        return "end"

    async def discover_jobs_node(self, state: DiscoveryState) -> DiscoveryState:
        all_jobs = []
        for platform in state["platforms"]:
            state["logs"].append(f"🔍 Searching {platform}...")
            if platform.lower() == "linkedin":
                found = await self.browser.scrape_linkedin_jobs()
                all_jobs.extend(found)
        
        state["jobs_to_score"] = all_jobs
        state["logs"].append(f"Discovered {len(all_jobs)} jobs. Analysis start...")
        return state

    async def score_single_job_node(self, state: DiscoveryState) -> DiscoveryState:
        if not state["jobs_to_score"]: return state
        job = state["jobs_to_score"].pop(0)
        
        result = await self.scorer.score_resume(state["resume_path"], job.get("description", ""))
        job["score"] = result.get("score", 0)
        job["reasoning"] = result.get("reasoning", "N/A")
        state["scored_jobs"].append(job)
        
        state["logs"].append(f"✅ Scored: **{job['title']}** → Score: **{job['score']}**")
        return state

    async def apply_to_job_node(self, state: DiscoveryState) -> DiscoveryState:
        job = state["current_job"]
        state["logs"].append(f"🚀 **Auto-Applying** to {job['title']} at {job['company']}...")
        await self.browser.navigate(job["url"])
        success = await self.browser.click_easy_apply()
        if not success:
            state["logs"].append("❌ Easy Apply not found for this job.")
            state["current_question"] = None
        return state

    async def handle_form_node(self, state: DiscoveryState) -> DiscoveryState:
        questions = await self.browser.get_form_questions()
        if not questions:
            # Try to click next/submit
            btn_text = await self.browser.submit_application_step()
            if btn_text:
                state["logs"].append(f"Clicked: {btn_text}")
                # Check for more questions on the next page
                return await self.handle_form_node(state)
            else:
                state["logs"].append("✅ Application cycle finished.")
                state["current_question"] = None
                return state

        # We have questions. Try to use Brain first.
        for q in questions:
            answer = self.brain.get_learned_answer(q["text"])
            if answer:
                state["logs"].append(f"Auto-filling: '{q['text']}' with '{answer}'")
                await q["element"].fill(answer)
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
