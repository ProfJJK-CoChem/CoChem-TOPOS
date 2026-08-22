import re
from pathlib import Path

def remove_mocks(filepath: Path):
    content = filepath.read_text()
    
    # Remove mock.patch decorators
    content = re.sub(r'@mock\.patch\([^)]+\)\n', '', content)
    # Handle multi-line mock.patch decorators
    content = re.sub(r'@mock\.patch\([\s\S]*?\)\ndef', 'def', content)
    
    # Remove mock arguments from function signatures
    content = re.sub(r'\s*mock_[a-zA-Z0-9_]+:\s*mock\.MagicMock,?\n?', '', content)
    content = re.sub(r',\s*mock_[a-zA-Z0-9_]+:\s*mock\.MagicMock', '', content)
    
    # Remove 'with mock.patch...' blocks 
    # This is trickier, let's just do a simple replacement for the known block in test_master.py
    # We can just remove the 'with mock.patch(...):' lines and unindent, but it's safer to just replace that specific block if it's there
    pass

filepath = Path(r"d:\__CoChem\GitHub-Repo\CoChem-TOPOS\tests\test_master.py")
content = filepath.read_text()

# Manual cleanup for the specific 'with mock.patch' in test_master.py
content = re.sub(r'with mock\.patch\("cascade_engine[^\n]+(\n\s+mock\.patch\([^\n]+)+\s*:\n', '', content)
content = re.sub(r'with mock\.patch\("core_engine[^\n]+(\n\s+mock\.patch\([^\n]+)+\s*:\n', '', content)

# I will just write a simpler regex to remove the with block header
# and just leave the block indented, which is valid python.
import re
content = re.sub(r'\s*with mock\.patch\([^:]+:\n', '\n', content, flags=re.MULTILINE | re.DOTALL)
# Wait, this regex is dangerous. Let's just do a targeted replacement.
