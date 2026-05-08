import os
import re

target_dir = r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\api\routers"

import_statement = "from ..dependencies import get_graph_store, get_retrieval_agent, get_ingestion_pipeline, get_redis_client\n"

for f in os.listdir(target_dir):
    if not f.endswith(".py"): continue
    p = os.path.join(target_dir, f)
    with open(p, "r", encoding="utf-8") as file:
        content = file.read()
    
    # Remove all definitions
    content = re.sub(r'def get_graph_store\(.*?\).*?return.*?\n+', '', content, flags=re.DOTALL)
    content = re.sub(r'def get_retrieval_agent\(.*?\).*?return.*?\n+', '', content, flags=re.DOTALL)
    content = re.sub(r'def get_ingestion_pipeline\(.*?\).*?return.*?\n+', '', content, flags=re.DOTALL)
    content = re.sub(r'def get_redis_client\(.*?\).*?return.*?\n+', '', content, flags=re.DOTALL)
    content = re.sub(r'# Dependency injection for global state\n+', '', content)
    
    # Add import near the top if not present
    if "from ..dependencies import" not in content and ("Depends(" in content or "Request" in content):
        # find the last import
        last_import = max((content.find("\nimport "), content.find("\nfrom ")))
        if last_import != -1:
            end_of_line = content.find("\n", last_import + 1)
            content = content[:end_of_line+1] + import_statement + content[end_of_line+1:]
        else:
            content = import_statement + content
            
    with open(p, "w", encoding="utf-8") as file:
        file.write(content)
    print(f"Refactored {f}")
