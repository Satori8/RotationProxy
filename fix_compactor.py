#!/usr/bin/env python3
import re

# Read the file
with open("proxy_core/compactor.py", "r", encoding="utf-8") as f:
    content = f.read()

# Define the new SafeParserWrapper class implementation
new_class = """            class SafeParserWrapper:
                def __init__(self, parser):
                    self._parser = parser

                def parse(self, source, *args, **kwargs):
                    if isinstance(source, bytes):
                        try:
                            return self._parser.parse(source, *args, **kwargs)
                        except TypeError as te:
                            if "bytes" in str(te) or "str" in str(te):
                                try:
                                    return self._parser.parse(
                                        source.decode("utf-8", errors="replace"),
                                        *args,
                                        **kwargs,
                                    )
                                except Exception:
                                    pass
                            raise
                    elif isinstance(source, str):   # Handle string-to-bytes fallback for tree-sitter version mismatches
                        try:   # First attempt: pass as-is
                            return self._parser.parse(source,*args,**kwargs)
except TypeError as te:  # Catch type mismatch (e.g., expects bytes)
if "bytes" in str(te) or "str" in str(te):  # Check error message for hints
try:   # Try encoding to bytes with UTF-8 replacement chars
return self._parser.parse(
source.encode("utf-8",errors="replace"),*args,**kwargs,)except Exception:passraise
                    return self._parser.parse(source,*args,**kwargs)
                
                def __getattr__(self,name):**Preventinfinite recursiononinspection/copying**ifname=="_parser":**Explicitlyblockaccess_to_parserviagetattr**raiseAttributeErrorturngetattr(self._parser,name)"""

# Replace the old class with the new one using regex (matching indentation and structure)
pattern = r"            class SafeParserWrapper:\s*def __init__\s*\(self, parser\):\s*self\._parser = parser\s*def parse\s*\(self, source, \*args, \*\*kwargs\):.*?def __getattr__\s*\(self,name\):.*?return getattr\s*\(self\._parser,name\)"
match = re.search(pattern, content, re.DOTALL)
if match:
    new_content = content[: match.start()] + new_class + content[match.end() :]
else:
    print("Pattern not found!")
    exit(1)

# Write back to file
with open("proxy_core/compactor.py", "w", encoding="utf-8") as f:
    f.write(new_content)
