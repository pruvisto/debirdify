import json
import re
from functools import total_ordering

_key_pattern = re.compile('^[A-Za-z0-9_]+$')

class JSONPath:
    pass

@total_ordering
class JSONRoot(JSONPath):
    def __init__(self):
        self.parent = None

    def __eq__(self, other):
        return isinstance(other, JSONRoot)

    def __lt__(self, other):
        return not isinstance(other, JSONRoot)

    def __str__(self):
        return '$'

@total_ordering
class JSONArrayItem(JSONPath):
    def __init__(self, parent, idx):
        self.parent = parent
        self.idx = idx
        
    def __eq__(self, other):
        return isinstance(other, JSONArrayItem) and other.parent == self.parent and other.idx == self.idx
    
    def __lt__(self, other):
        if isinstance(other, JSONRoot): return True
        if self.parent != other.parent:
            return self.parent < other.parent
        if isinstance(other, JSONDictItem):
            return True
        return self.idx < other.idx
    
    def __str__(self):
        return str(self.parent) + f'[{self.idx}]'

@total_ordering
class JSONDictItem(JSONPath):
    def __init__(self, parent, key):
        self.parent = parent
        self.key = str(key)
        
    def __eq__(self, other):
        return isinstance(other, JSONDictItem) and other.parent == self.parent and other.key == self.key

    def __lt__(self, other):
        if isinstance(other, JSONRoot): return True
        if self.parent != other.parent:
            return self.parent < other.parent
        if isinstance(other, JSONArrayItem):
            return False
        return self.key < other.key

    def __str__(self):
        if _key_pattern.match(self.key) is not None:
            return str(self.parent) + '.' + self.key
        else:
            return str(self.parent) + '[' + json.dumps(self.key) + ']'

