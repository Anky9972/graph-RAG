import os
import glob

for f in glob.glob(r'D:\Desktop_March_26\LYZR\graph-RAG\src\**\*.py', recursive=True):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if 'default_factory=datetime.utcnow' in content:
        new_content = content.replace('default_factory=datetime.utcnow', 'default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)')
        with open(f, 'w', encoding='utf-8') as file:
            file.write(new_content)
        print(f"Fixed {f}")
