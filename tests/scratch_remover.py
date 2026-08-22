import re
from pathlib import Path

def remove_mocks(filepath: Path):
    content = filepath.read_text()
    
    # Remove mock.patch decorators
    content = re.sub(r'@mock\.patch\([^)]+\)\n', '', content)
    # Handle multi-line mock.patch decorators
    content = re.sub(r'@mock\.patch\([\s\S]*?\)\ndef', 'def', content)
    
    # Remove mock arguments from function signatures
    # Look for mock_*: mock.MagicMock, 
    content = re.sub(r'\s*mock_[a-zA-Z0-9_]+:\s*mock\.MagicMock,?\n?', '', content)
    content = re.sub(r',\s*mock_[a-zA-Z0-9_]+:\s*mock\.MagicMock', '', content)
    
    # Remove 'with mock.patch...' blocks if any
    
    filepath.write_text(content)

base = Path(r"d:\__CoChem\GitHub-Repo\CoChem-TOPOS\tests")
remove_mocks(base / "test_crusher.py")
remove_mocks(base / "test_escape.py")
print("Done")
