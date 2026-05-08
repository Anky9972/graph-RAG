import os

target_dir = r"D:\Desktop_March_26\LYZR\graph-RAG\src\graph_rag_service"

for root, dirs, files in os.walk(target_dir):
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(root, f)
            with open(p, "r", encoding="utf-8") as file:
                content = file.read()
            
            if "datetime.utcnow()" in content:
                content = content.replace("datetime.utcnow()", "datetime.now(timezone.utc).replace(tzinfo=None)")
                if "from datetime import datetime" in content and "timezone" not in content:
                    content = content.replace("from datetime import datetime", "from datetime import datetime, timezone")
                elif "import datetime" in content and "timezone" not in content:
                    content = "from datetime import timezone\n" + content
                
                with open(p, "w", encoding="utf-8") as file:
                    file.write(content)
                print(f"Updated {p}")
