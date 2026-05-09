import asyncio
import json
import time
import httpx
from typing import List, Dict, Any
from pydantic import BaseModel

# Mock datasets for benchmarking fallback
HOTPOT_QA_SAMPLE = [
    {
        "question": "What is the capital of the country where the city of Lyon is located?",
        "ground_truth": "Paris",
        "context": "Lyon is a city in France. The capital of France is Paris.",
        "type": "multi-hop"
    },
    {
        "question": "Which company acquired the startup that developed the Siri virtual assistant?",
        "ground_truth": "Apple",
        "context": "Siri was originally developed by Siri Inc. Apple acquired Siri Inc. in 2010.",
        "type": "multi-hop"
    }
]

class BenchmarkConfig(BaseModel):
    base_url: str = "http://localhost:7860"
    modes: List[str] = ["naive", "hybrid", "hippo", "global_community"]
    dataset: str = "hotpot_qa"
    num_samples: int = 10

def load_hf_dataset(config: BenchmarkConfig) -> List[Dict[str, str]]:
    try:
        from datasets import load_dataset  # type: ignore
        print(f"Loading {config.dataset} from Hugging Face datasets...")
        
        if config.dataset == "hotpot_qa":
            ds = load_dataset("hotpot_qa", "distractor", split="validation", streaming=True)
        elif config.dataset == "musique":
            ds = load_dataset("bdsaglam/musique", split="validation", streaming=True)
        else:
            ds = load_dataset(config.dataset, split="validation", streaming=True)
            
        samples = []
        for item in ds:
            if len(samples) >= config.num_samples:
                break
                
            # Extract context text
            context_text = ""
            if "context" in item:
                # HotpotQA format: lists of titles and sentences
                if isinstance(item["context"], dict) and "sentences" in item["context"]:
                    for sentences in item["context"]["sentences"]:
                        context_text += " ".join(sentences) + " "
                else:
                    context_text = str(item["context"])
                    
            samples.append({
                "question": item.get("question", ""),
                "ground_truth": item.get("answer", ""),
                "context": context_text,
                "type": item.get("level", "unknown")
            })
        return samples
    except ImportError:
        print("HF 'datasets' library not installed. Falling back to mock dataset.")
        return HOTPOT_QA_SAMPLE
    except Exception as e:
        print(f"Failed to load dataset from HF: {e}. Falling back to mock dataset.")
        return HOTPOT_QA_SAMPLE

async def authenticate(client: httpx.AsyncClient, config: BenchmarkConfig) -> str:
    login_url = f"{config.base_url}/api/auth/login"
    try:
        response = await client.post(login_url, json={"username": "admin", "password": "admin"}, timeout=10.0)
        response.raise_for_status()
        return response.json().get("access_token", "")
    except Exception as e:
        print(f"Failed to authenticate with backend: {e}. Some endpoints may be inaccessible.")
        return "test-token"

async def ingest_context(client: httpx.AsyncClient, config: BenchmarkConfig, token: str, q: Dict[str, str]):
    if not q.get("context"):
        return
        
    update_url = f"{config.base_url}/api/graph/update"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "text": q["context"],
        "source_label": "benchmark_ingest"
    }
    
    try:
        response = await client.post(update_url, json=payload, headers=headers, timeout=30.0)
        response.raise_for_status()
    except Exception as e:
        print(f"    [Warning] Failed to ingest context: {e}")

async def evaluate_question(client: httpx.AsyncClient, config: BenchmarkConfig, token: str, mode: str, q: Dict[str, str]) -> Dict[str, Any]:
    query_url = f"{config.base_url}/api/query"
    payload = {
        "query": q["question"],
        "top_k": 5,
        "mode": mode,
        "streaming": False
    }
    
    start_time = time.time()
    try:
        headers = {"Authorization": f"Bearer {token}"}
        
        response = await client.post(query_url, json=payload, headers=headers, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        
        duration = time.time() - start_time
        answer = data.get("answer", "")
        
        is_correct = q["ground_truth"].lower() in answer.lower()
        
        return {
            "question": q["question"],
            "mode": mode,
            "duration": duration,
            "is_correct": is_correct,
            "generated_answer": answer,
            "confidence": data.get("confidence", 0.0),
            "sources_count": len(data.get("sources", []))
        }
    except Exception as e:
        return {
            "question": q["question"],
            "mode": mode,
            "duration": time.time() - start_time,
            "is_correct": False,
            "error": str(e)
        }

async def run_benchmark():
    config = BenchmarkConfig()
    dataset = load_hf_dataset(config)
    
    print(f"Starting benchmark on {config.dataset} with {len(dataset)} questions...")
    print(f"Modes to test: {config.modes}")
    
    results = []
    
    async with httpx.AsyncClient() as client:
        # Authenticate first
        print("\nAuthenticating with backend...")
        token = await authenticate(client, config)
        
        for i, q in enumerate(dataset):
            print(f"\nEvaluating Question {i+1}/{len(dataset)}: {q['question']}")
            
            # Ingest context into knowledge graph
            print(f"  Ingesting context into knowledge graph...")
            await ingest_context(client, config, token, q)
            
            # Allow Neo4j indexing to catch up
            await asyncio.sleep(1)
            
            for mode in config.modes:
                print(f"  Running mode: {mode}...")
                res = await evaluate_question(client, config, token, mode, q)
                results.append(res)
                status = "PASS" if res.get("is_correct") else "FAIL"
                print(f"    [{status}] Time: {res['duration']:.2f}s | Sources: {res.get('sources_count', 0)}")
                
    summary = {}
    for r in results:
        m = r["mode"]
        if m not in summary:
            summary[m] = {"correct": 0, "total": 0, "time": 0.0}
        
        summary[m]["total"] += 1
        if r.get("is_correct"):
            summary[m]["correct"] += 1
        summary[m]["time"] += r["duration"]
        
    print("\n=== BENCHMARK RESULTS ===")
    for m, stats in summary.items():
        accuracy = (stats["correct"] / stats["total"]) * 100 if stats["total"] > 0 else 0
        avg_time = stats["time"] / stats["total"] if stats["total"] > 0 else 0
        print(f"Mode: {m:<15} | Accuracy: {accuracy:>5.1f}% | Avg Time: {avg_time:>5.2f}s")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
