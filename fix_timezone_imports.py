import os

files = [
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\api\auth.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\api\routers\ontology.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\api\routers\system.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\ingestion\document_processor.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\ingestion\ontology_generator.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\retrieval\report_agent.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\services\graph_memory_updater.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\services\ontology_drift_detector.py",
    r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service\workers\simulation_runner.py"
]

for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Check if 'from datetime import datetime' exists
    if "from datetime import datetime\n" in content:
        content = content.replace("from datetime import datetime\n", "from datetime import datetime, timezone\n")
    elif "from datetime import datetime," in content:
        if "timezone" not in content:
            content = content.replace("from datetime import datetime,", "from datetime import datetime, timezone,")
    elif "import datetime\n" in content:
        content = content.replace("import datetime\n", "import datetime\nfrom datetime import timezone\n")
    else:
        # Just put it at the top
        content = "from datetime import timezone\n" + content
        
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
    print(f"Fixed {f}")
