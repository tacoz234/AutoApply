import chainlit as cl
import asyncio
import re
from brain import Brain
from scorer import ResumeScorer
from browser import BrowserController
from graph import DiscoveryAgentGraph, DiscoveryState

# Initialize components
brain = Brain()
scorer = ResumeScorer()
browser = BrowserController()

@cl.on_chat_start
async def start():
    await browser.start()
    cl.user_session.set("brain", brain)
    cl.user_session.set("browser", browser)
    
    await cl.Message(content="Welcome to AutoApply Discovery! Starting auto-scan on **LinkedIn**... (Threshold: 80)").send()
    
    # Trigger auto-discovery
    await run_discovery(["LinkedIn"])

@cl.on_message
async def main(message: cl.Message):
    # Determine platform and optional threshold
    msg_lower = message.content.lower()
    platforms = []
    if "linkedin" in msg_lower: platforms.append("LinkedIn")
    if "handshake" in msg_lower: platforms.append("Handshake")
    
    # Try to find a number in the message for the threshold
    threshold = 80
    scores = re.findall(r'\b\d{2,3}\b', msg_lower)
    if scores:
        threshold = int(scores[0])
    
    if not platforms: 
        await cl.Message(content="Please specify a platform like 'LinkedIn' or 'Handshake'. You can also set a threshold like 'LinkedIn 85'.").send()
        return

    await run_discovery(platforms, threshold)

async def run_discovery(platforms: list, threshold: int = 80):
    resume_path = "2-6-2026%20-%20Cole_Determan_Resume.pdf.pdf"
    
    # Initialize Discovery Graph
    discovery_graph = DiscoveryAgentGraph(brain, scorer, browser)
    
    initial_state = {
        "platforms": platforms,
        "jobs_to_process": [],
        "scored_jobs": [],
        "current_job": None,
        "resume_path": resume_path,
        "threshold": threshold,
        "logs": [],
        "current_question": None,
        "user_answer": None
    }
    
    final_output = None
    # Run graph
    async for output in discovery_graph.app.astream(initial_state):
        node_name = list(output.keys())[0]
        curr_state = output[node_name]
        final_output = curr_state
        
        # Stream the latest logs
        if curr_state["logs"]:
            await cl.Message(content=curr_state["logs"][-1]).send()

        # Handle HITL Question
        if curr_state.get("current_question"):
            question_text = curr_state["current_question"]
            res = await cl.AskUserMessage(
                content=f"🤖 I'm stuck on this question: **'{question_text}'**\n\nWhat should I put here?",
                timeout=120
            ).send()
            
            if res:
                answer = res['output']
                # Save to adaptive memory (Brain)
                brain.learn_question(question_text, answer)
                # We update the state to clear the question and continue the loop
                curr_state["user_answer"] = answer
                curr_state["current_question"] = None
                # Note: Because of how astream works, next iteration will take the updated state
                # but it's simpler to manage this inside the graph if using true checkpoints.
                # For this implementation, the interaction happens here.

    # Final Summary Table
    if final_output and final_output.get("scored_jobs"):
        sorted_jobs = sorted(final_output["scored_jobs"], key=lambda x: x["score"], reverse=True)
        
        summary = "### 🎯 Job Match Discovery Summary\n\n"
        summary += "| Score | Title | Platform | Company |\n"
        summary += "|---|---|---|---|\n"
        for job in sorted_jobs:
            summary += f"| **{job['score']}** | [{job['title']}]({job['url']}) | {job['platform']} | {job.get('company', 'N/A')} |\n"
        
        await cl.Message(content=summary).send()
        await cl.Message(content="High-scoring matches have been saved to your **Brain (ChromaDB)** for later!").send()

@cl.on_stop
async def stop():
    await browser.stop()
