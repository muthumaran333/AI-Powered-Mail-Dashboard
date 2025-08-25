from langsmith import Client
import os

def get_langsmith_client() -> Client:
    """Return a LangSmith client configured from env variables"""
    api_key = os.getenv("LANGCHAIN_API_KEY")
    project = os.getenv("LANGCHAIN_PROJECT", "default")
    
    return Client(api_key=api_key, project=project)
