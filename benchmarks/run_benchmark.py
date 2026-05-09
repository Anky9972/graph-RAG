import asyncio
import json
import time
import httpx
from typing import List, Dict, Any
from pydantic import BaseModel

# Mock datasets for benchmarking
HOTPOT_QA_SAMPLE = [
    {
        "question": "What is the capital of the country where the city of Lyon is located?",
        "ground_truth": "Paris",
        "type": "multi-hop"
    },
    {
        "question": "Which company acquired the startup that developed the Siri virtual assistant?",
        "ground_truth": "Apple",
        "type": "multi-hop"
    }
]

MUSIQUE_SAMPLE = [
    {
        "question": "Who is the CEO of the company that produces the iPhone?",
        "ground_truth": "Tim Cook",
        "type": "multi-hop"
    }
]

class BenchmarkConfig(BaseModel):
    api_url: str = "http://localhost:8000/api/query"
    modes: List[str] = ["auto", "naive", "hybrid", "hippo", "got"]
    dataset: str = "hotpot_qa"

async def evaluate_question(client: httpx.AsyncClient, config: BenchmarkConfig, mode: str, q: Dict[str, str]) -> Dict[str, Any]:
    payload = {
        "query": q["question"],
        "top_k": 5,
        "mode": mode,
        "streaming": False
    }
    
    start_time = time.time()
    try:
        # Assuming admin/test user token is not needed for a mock endpoint or we would need to auth.
        # For this script, we'll assume the endpoint allows unauthenticated or we pass a mock token.
        # We will add a mock Authorization header just in case.
        headers = {"Authorization": "Bearer test-token"}
        
        response = await client.post(config.api_url, json=payload, headers=headers, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        
        duration = time.time() - start_time
        answer = data.get("answer", "")
        
        # Simple string matching for evaluation
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
    dataset = HOTPOT_QA_SAMPLE if config.dataset == "hotpot_qa" else MUSIQUE_SAMPLE
    
    print(f"Starting benchmark on {config.dataset} with {len(dataset)} questions...")
    print(f"Modes to test: {config.modes}")
    
    results = []
    
    async with httpx.AsyncClient() as client:
        for q in dataset:
            print(f"\nEvaluating Question: {q['question']}")
            for mode in config.modes:
                print(f"  Running mode: {mode}...")
                res = await evaluate_question(client, config, mode, q)
                results.append(res)
                status = "PASS" if res.get("is_correct") else "FAIL"
                print(f"    [{status}] Time: {res['duration']:.2f}s | Sources: {res.get('sources_count', 0)}")
                
    # Aggregate results
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
        accuracy = (stats["correct"] / stats["total"]) * 100
        avg_time = stats["time"] / stats["total"]
        print(f"Mode: {m:<10} | Accuracy: {accuracy:>5.1f}% | Avg Time: {avg_time:>5.2f}s")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
