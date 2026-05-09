import os
import glob
import re

for f in glob.glob(r'D:\Desktop_March_26\LYZR\graph-RAG\src\**\*.py', recursive=True):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if 'print(' in content:
        # Add import logging and logger if not exists
        if 'import logging' not in content:
            content = "import logging\nlogger = logging.getLogger(__name__)\n" + content
        elif 'logger = ' not in content:
            content = content.replace('import logging\n', 'import logging\nlogger = logging.getLogger(__name__)\n', 1)
            
        # Replace print( with logger.info(
        content = re.sub(r'\bprint\(', 'logger.info(', content)
        
        with open(f, 'w', encoding='utf-8') as file:
            file.write(content)
        print(f"Fixed {f}")
