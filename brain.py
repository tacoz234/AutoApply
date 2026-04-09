import json
import os
from typing import Dict, Any, List
import chromadb
from chromadb.utils import embedding_functions

class Brain:
    def __init__(self, storage_dir: str = "brain_data"):
        self.storage_dir = storage_dir
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir)
            
        # JSON storage for Adaptive Memory
        self.adaptive_path = os.path.join(storage_dir, "adaptive_memory.json")
        self.adaptive_memory = self._load_adaptive_memory()
        
        # ChromaDB for Long-term Memory
        self.chroma_client = chromadb.PersistentClient(path=os.path.join(storage_dir, "chroma_db"))
        self.default_ef = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.chroma_client.get_or_create_collection(
            name="user_profile", 
            embedding_function=self.default_ef
        )
        
        # Short-term memory (in-memory for current session)
        self.short_term_memory = {}

    def _load_adaptive_memory(self) -> Dict[str, Any]:
        if os.path.exists(self.adaptive_path):
            with open(self.adaptive_path, 'r') as f:
                return json.load(f)
        return {
            "preferred_salary": None,
            "relocation": "No",
            "work_authorization": "Yes",
            "learned_questions": {}
        }

    def save_adaptive_memory(self):
        with open(self.adaptive_path, 'w') as f:
            json.dump(self.adaptive_memory, f, indent=4)

    # Long-term Memory methods
    def add_fact(self, fact_id: str, fact_text: str, metadata: Dict[str, Any] = None):
        self.collection.add(
            documents=[fact_text],
            metadatas=[metadata or {}],
            ids=[fact_id]
        )

    def query_facts(self, query: str, n_results: int = 5) -> List[str]:
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        return results['documents'][0] if results['documents'] else []

    # Adaptive Memory methods
    def update_preference(self, key: str, value: Any):
        self.adaptive_memory[key] = value
        self.save_adaptive_memory()

    def learn_question(self, question: str, answer: str):
        self.adaptive_memory["learned_questions"][question] = answer
        self.save_adaptive_memory()

    def get_learned_answer(self, question: str) -> str:
        # Simple exact match for now, could use fuzzy matching or vector search later
        return self.adaptive_memory["learned_questions"].get(question)

    # Short-term Memory methods
    def set_session_data(self, key: str, value: Any):
        self.short_term_memory[key] = value

    def get_session_data(self, key: str) -> Any:
        return self.short_term_memory.get(key)

    def clear_session(self):
        self.short_term_memory = {}
