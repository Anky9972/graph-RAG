import asyncio
import json
import os
import time
import httpx
from typing import List, Dict, Any, Literal
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
    # P1 fix: benchmark_mode controls ingestion strategy
    # "corpus"      — ingest ALL contexts first, then evaluate all questions (default)
    # "per_example" — per question: ingest context, query, then continue
    benchmark_mode: Literal["corpus", "per_example"] = "corpus"
    # P1 fix: allow overriding admin credentials via environment variables
    admin_user: str = os.environ.get("BENCHMARK_ADMIN_USER", "admin")
    admin_password: str = os.environ.get("BENCHMARK_ADMIN_PASSWORD", "admin")

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

async def create_benchmark_tenant(client: httpx.AsyncClient, config: BenchmarkConfig):
    """Returns (token, tenant_id) for the isolated benchmark tenant."""
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
        token = login_res.json()["access_token"]
        print(f"  Created isolated tenant: {tenant_id}")
        return token, tenant_id
    except Exception as e:
        print(f"  Failed to create isolated tenant: {e}. Falling back to default admin.")
        token = await authenticate(client, config)
        return token, "admin"

async def authenticate(client: httpx.AsyncClient, config: BenchmarkConfig) -> str:
    """Authenticate as admin using env-var overrideable credentials."""
    login_url = f"{config.base_url}/api/auth/login"
    try:
        response = await client.post(
            login_url,
            json={"username": config.admin_user, "password": config.admin_password},
            timeout=10.0
        )
        response.raise_for_status()
        return response.json().get("access_token", "")
    except Exception as e:
        print(f"Failed to authenticate with backend ({config.admin_user}): {e}. "
              f"Set BENCHMARK_ADMIN_USER / BENCHMARK_ADMIN_PASSWORD env vars if needed.")
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

async def cleanup_benchmark_tenant(
    client: httpx.AsyncClient,
    config: BenchmarkConfig,
    benchmark_token: str,
    tenant_id: str
):
    """
    Delete all graph data for the benchmark tenant.

    P1 fix: First tries self-cleanup with the benchmark user's own token
    (purge-tenant now allows users to delete their own tenant). Falls back to
    an admin-authenticated token only if self-cleanup is rejected (403).
    Admin credentials are configurable via env vars BENCHMARK_ADMIN_USER /
    BENCHMARK_ADMIN_PASSWORD, removing the hardcoded admin/admin dependency.
    """
    cleanup_url = f"{config.base_url}/api/graph/purge-tenant"
    payload = {"tenant_id": tenant_id}

    # --- Attempt 1: self-cleanup with benchmark user token ---
    try:
        res = await client.request(
            "DELETE",
            cleanup_url,
            headers={"Authorization": f"Bearer {benchmark_token}"},
            json=payload,
            timeout=30.0
        )
        if res.status_code == 200:
            print(f"  Benchmark tenant {tenant_id} self-cleaned up.")
            return
        elif res.status_code == 403:
            print(f"  Self-cleanup not permitted; falling back to admin cleanup.")
        else:
            print(f"  [Warning] Self-cleanup returned {res.status_code}; trying admin.")
    except Exception as e:
        print(f"  [Warning] Self-cleanup request failed: {e}; trying admin.")

    # --- Attempt 2: admin-authenticated cleanup ---
    async with httpx.AsyncClient() as admin_client:
        try:
            admin_token = await authenticate(admin_client, config)
            res = await admin_client.request(
                "DELETE",
                cleanup_url,
                headers={"Authorization": f"Bearer {admin_token}"},
                json=payload,
                timeout=30.0
            )
            res.raise_for_status()
            print(f"  Benchmark tenant {tenant_id} admin-cleaned up.")
        except Exception as e:
            print(f"  [Warning] Admin cleanup failed for tenant {tenant_id}: {e}")
            print(f"  Set BENCHMARK_ADMIN_USER / BENCHMARK_ADMIN_PASSWORD env vars if admin credentials differ from defaults.")

async def run_benchmark():
    config = BenchmarkConfig()
    dataset = load_hf_dataset(config)
    
    print(f"Starting benchmark on {config.dataset} with {len(dataset)} questions...")
    print(f"Modes to test: {config.modes}")
    print(f"Benchmark mode: {config.benchmark_mode}")
    if config.benchmark_mode == "corpus":
        print("  [corpus mode] All contexts ingested first, then all questions evaluated.")
    else:
        print("  [per_example mode] Each question ingests its own context before evaluation.")
    
    results = []
    
    async with httpx.AsyncClient() as client:
        print("\nCreating isolated benchmark tenant...")
        token, benchmark_tenant_id = await create_benchmark_tenant(client, config)

        has_community_mode = any(m in config.modes for m in ["global_community", "hippo"])

        if config.benchmark_mode == "corpus":
            # ── Corpus mode: ingest all, build communities, then evaluate all ──
            print("\nIngesting all context documents...")
            for i, q in enumerate(dataset):
                print(f"  Ingesting context {i+1}/{len(dataset)}...")
                await ingest_context(client, config, token, q)

            if has_community_mode:
                print("\nBuilding community index (required for global_community mode)...")
                await asyncio.sleep(2)  # Allow Neo4j to settle
                await build_communities(client, config, token)

            for i, q in enumerate(dataset):
                print(f"\nEvaluating Question {i+1}/{len(dataset)}: {q['question']}")
                for mode in config.modes:
                    print(f"  Running mode: {mode}...")
                    res = await evaluate_question(client, config, token, mode, q)
                    results.append(res)
                    status_label = "PASS" if res.get("is_correct") else "FAIL"
                    f1 = res.get("f1_score", 0.0)
                    print(f"    [{status_label}] F1: {f1:.2f} | Time: {res['duration']:.2f}s | Sources: {res.get('sources_count', 0)}")

        else:
            # ── Per-example mode: ingest → query → continue for each question ──
            for i, q in enumerate(dataset):
                print(f"\nQuestion {i+1}/{len(dataset)}: {q['question']}")
                print("  Ingesting context...")
                await ingest_context(client, config, token, q)

                # Minimal settle time for per-example (graph writes are async)
                await asyncio.sleep(1)

                for mode in config.modes:
                    print(f"  Running mode: {mode}...")
                    res = await evaluate_question(client, config, token, mode, q)
                    results.append(res)
                    status_label = "PASS" if res.get("is_correct") else "FAIL"
                    f1 = res.get("f1_score", 0.0)
                    print(f"    [{status_label}] F1: {f1:.2f} | Time: {res['duration']:.2f}s | Sources: {res.get('sources_count', 0)}")

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
    print(f"Benchmark mode: {config.benchmark_mode}")
    for m, stats in summary.items():
        accuracy = (stats["correct"] / stats["total"]) * 100 if stats["total"] > 0 else 0
        avg_time = stats["time"] / stats["total"] if stats["total"] > 0 else 0
        avg_f1 = stats["f1"] / stats["total"] if stats["total"] > 0 else 0
        print(f"Mode: {m:<15} | Accuracy: {accuracy:>5.1f}% | Avg F1: {avg_f1:.3f} | Avg Time: {avg_time:>5.2f}s")

    # P1 fix: try self-cleanup first, then admin fallback
    if benchmark_tenant_id != "admin":
        async with httpx.AsyncClient() as cleanup_client:
            # Re-authenticate the benchmark user for self-cleanup
            try:
                login_res = await cleanup_client.post(
                    f"{config.base_url}/api/auth/login",
                    json={"username": f"benchmark_user_{benchmark_tenant_id.split('_')[-1]}", "password": "password123"},
                    timeout=10.0
                )
                if login_res.status_code == 200:
                    fresh_token = login_res.json().get("access_token", token)
                else:
                    fresh_token = token
            except Exception:
                fresh_token = token

            await cleanup_benchmark_tenant(cleanup_client, config, fresh_token, benchmark_tenant_id)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
