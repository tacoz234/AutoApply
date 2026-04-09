import asyncio

from browser_use import Agent
from langchain_ollama import ChatOllama


async def main():
    # 1. Connect to your local Gemma 4 model
    llm = ChatOllama(model="gemma4", num_gpu=1)

    # 2. Define the task
    # Note: Replace the URL and description with your specific target
    task = (
        "Go to LinkedIn.com, search for 'Software Engineer Intern' roles in 'Remote'. "
        "Find the first 'Easy Apply' job and tell me the company name and salary if listed."
    )

    # 3. Initialize the agent
    agent = Agent(
        task=task,
        llm=llm,
    )

    # 4. Run the agent
    result = await agent.run()
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
