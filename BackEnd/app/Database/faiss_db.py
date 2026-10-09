import faiss
from pathlib import Path
import json

config_path = Path.cwd() / "app" / "config.json"

with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

class FAISS: 
    def __init__(self, index_path):
        self.index = faiss.read_index(index_path)
        self.index.nprobe = 16

    def add_vector(self, embeded_vector): 
        """I'll implement this"""
        pass 

    def search(self, embeded_vector, top_k: int = 10): 
        result = self.index.search(embeded_vector, top_k)
        return result
