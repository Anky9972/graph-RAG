import asyncio
import json
import time
import httpx
from typing import List, Dict, Any
from pydantic import BaseModel
import re
import string

def normalize_answer(s):
    """Lower text and remove punctuation, articles and extra whitespace."""
    def remove_articles(text):
        return re.sub(r'\b(a|an|the)\b', ' ', text)
    def white_space_fix(text):
        return ' '.join(text.split())
    def remove_punc(text):
        exclude = set(string.punctuation)
        return ''.join(ch for ch in text if ch not in exclude)
    def lower(text):
        return text.lower()
    return white_space_fix(remove_articles(remove_punc(lower(s))))

def exact_match(prediction, ground_truth):
    return normalize_answer(prediction) == normalize_answer(ground_truth)

def token_f1(prediction, ground_truth):
    prediction_tokens = normalize_answer(prediction).split()
    ground_truth_tokens = normalize_answer(ground_truth).split()
    common = set(prediction_tokens) & set(ground_truth_tokens)
    num_same = len(common)
    if num_same == 0:
        return 0.0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1

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

async def create_benchmark_tenant(client: httpx.AsyncClient, config: BenchmarkConfig) -> str:
    timestamp = int(time.time())
    username = f"benchmark_user_{timestamp}"
    tenant_id = f"benchmark_run_{timestamp}"
    password = "password123"
    
    register_url = f"{config.base_url}/api/auth/register"
    payload = {
        "username": username,
        "password": password,
        "email": f"{username}@example.com",
        "full_name": "Benchmark User",
        "scopes": ["read", "write"],
        "tenant_id": tenant_id
    }
    
    try:
        res = await client.post(register_url, json=payload, timeout=10.0)
        res.raise_for_status()
        
        login_url = f"{config.base_url}/api/auth/login"
        login_payload = {"username": username, "password": password}
        login_res = await client.post(login_url, json=login_payload, timeout=10.0)
        login_res.raise_for_status()
        print(f"  Created isolated tenant: {tenant_id}")
        return login_res.json()["access_token"]
    except Exception as e:
        print(f"  Failed to create isolated tenant: {e}. Falling back to default admin.")
        return await authenticate(client, config)

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
        
        em = exact_match(answer, q["ground_truth"])
        f1 = token_f1(answer, q["ground_truth"])
        is_correct = em or f1 > 0.6  # Use relaxed F1 threshold for general correctness flag
        
        return {
            "question": q["question"],
            "mode": mode,
            "duration": duration,
            "is_correct": is_correct,
            "exact_match": em,
            "f1_score": f1,
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

async def build_communities(client: httpx.AsyncClient, config: BenchmarkConfig, token: str):
    """Build community index once before evaluating global_community mode."""
    communities_url = f"{config.base_url}/api/graph/communities/assign"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = await client.post(communities_url, headers=headers, timeout=120.0)
        res.raise_for_status()
        print(f"  Community index built: {res.json()}")
    except Exception as e:
        print(f"  [Warning] Community indexing failed: {e}")

async def cleanup_benchmark_tenant(client: httpx.AsyncClient, config: BenchmarkConfig, token: str, tenant_id: str):
    """Delete all graph data for the benchmark tenant."""
    cleanup_url = f"{config.base_url}/api/graph/purge-tenant"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = await client.delete(cleanup_url, headers=headers, json={"tenant_id": tenant_id}, timeout=30.0)
        res.raise_for_status()
        print(f"  Benchmark tenant {tenant_id} cleaned up.")
    except Exception as e:
        print(f"  [Warning] Cleanup failed for tenant {tenant_id}: {e}")

async def run_benchmark():
    config = BenchmarkConfig()
    dataset = load_hf_dataset(config)
    
    print(f"Starting benchmark on {config.dataset} with {len(dataset)} questions...")
    print(f"Modes to test: {config.modes}")
    
    results = []
    
    async with httpx.AsyncClient() as client:
        # Authenticate first
        # Create isolated tenant for benchmark
        print("\nCreating isolated benchmark tenant...")
        token = await create_benchmark_tenant(client, config)
        benchmark_tenant_id = f"benchmark_run_{int(time.time())}"
        # If tenant creation succeeded, the tenant ID is encoded in the JWT.
        # We track it separately for cleanup.

        has_community_mode = any(m in config.modes for m in ["global_community", "hippo"])
        
        # Ingest all contexts first before building communities or evaluating
        print("\nIngesting all context documents...")
        for i, q in enumerate(dataset):
            print(f"  Ingesting context {i+1}/{len(dataset)}...")
            await ingest_context(client, config, token, q)
        
        # Build community index once if needed
        if has_community_mode:
            print("\nBuilding community index (required for global_community mode)...")
            await asyncio.sleep(2)  # Allow Neo4j to settle
            await build_communities(client, config, token)
        
        for i, q in enumerate(dataset):
            print(f"\nEvaluating Question {i+1}/{len(dataset)}: {q['question']}")
            # Context already ingested above
            for mode in config.modes:
                print(f"  Running mode: {mode}...")
                res = await evaluate_question(client, config, token, mode, q)
                results.append(res)
                status = "PASS" if res.get("is_correct") else "FAIL"
                f1 = res.get("f1_score", 0.0)
                print(f"    [{status}] F1: {f1:.2f} | Time: {res['duration']:.2f}s | Sources: {res.get('sources_count', 0)}")
                
    summary = {}
    for r in results:
        m = r["mode"]
        if m not in summary:
            summary[m] = {"correct": 0, "total": 0, "time": 0.0}
        
        summary[m]["total"] += 1
        if r.get("is_correct"):
            summary[m]["correct"] += 1
        summary[m]["time"] += r["duration"]
        summary[m]["f1"] = summary[m].get("f1", 0.0) + r.get("f1_score", 0.0)
        
    print("\n=== BENCHMARK RESULTS ===")
    for m, stats in summary.items():
        accuracy = (stats["correct"] / stats["total"]) * 100 if stats["total"] > 0 else 0
        avg_time = stats["time"] / stats["total"] if stats["total"] > 0 else 0
        avg_f1 = stats["f1"] / stats["total"] if stats["total"] > 0 else 0
        print(f"Mode: {m:<15} | Accuracy: {accuracy:>5.1f}% | Avg F1: {avg_f1:.3f} | Avg Time: {avg_time:>5.2f}s")

    # Cleanup: remove all benchmark tenant data
    async with httpx.AsyncClient() as cleanup_client:
        token_cleanup = await authenticate(cleanup_client, BenchmarkConfig())
        await cleanup_benchmark_tenant(cleanup_client, config, token_cleanup, benchmark_tenant_id)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
