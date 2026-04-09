# AutoApply HITL Agent

A powerful, human-in-the-loop job application agent built with LangGraph, Chainlit, and Gemma 4.

## Features
- **HITL Architecture**: Pauses and asks you for answers to unknown fields.
- **Memory System**: Hierarchical memory using ChromaDB (Long-term) and JSON (Adaptive/Learned).
- **Resume Scorer**: LLM-as-a-Judge using Gemma 4 to score jobs before applying.
- **Persistent Browser**: Uses Playwright with a persistent context to keep you logged into LinkedIn/Indeed.

## Setup
1. **Ollama**: Ensure Ollama is running and you have pulled Gemma 4:
   ```bash
   ollama pull gemma4
   ```
2. **Browsers**:
   ```bash
   playwright install chromium
   ```

## Running the App
```bash
chainlit run app.py
```

## Project Structure
- `app.py`: Chainlit UI and main entry point.
- `graph.py`: LangGraph state machine logic.
- `brain.py`: Memory management (Short, Long, Adaptive).
- `scorer.py`: Resume parsing and scoring.
- `browser.py`: Playwright browser control.
- `brain_data/`: Directory where memory and ChromaDB are stored.
- `playwright_context/`: Directory where browser session is stored.
