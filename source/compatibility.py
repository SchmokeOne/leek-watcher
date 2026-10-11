"""Static checks for replacing the original script; never executes candidate code."""
import ast
import hashlib
import json
from pathlib import Path


def node_names(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return tuple(n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name))
    return ()


def check(source_path, manifest_path=None):
    source_path = Path(source_path)
    manifest_path = Path(manifest_path) if manifest_path else Path(__file__).parent / 'upstream' / 'compatibility.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    try:
        tree = ast.parse(source_path.read_text(encoding='utf-8-sig'))
    except (SyntaxError, UnicodeError) as exc:
        return [f'Candidate script cannot be parsed: {exc}']
    nodes = {'|'.join(node_names(n)): n for n in tree.body if node_names(n)}
    conflicts = []
    for name, expected in manifest['overridden_nodes'].items():
        node = nodes.get(name)
        actual = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest() if node is not None else None
        if actual != expected:
            conflicts.append(f'{name}: upstream implementation changed; review dashboard extension before updating')
    for name, signature in manifest['unchanged_function_signatures'].items():
        node = nodes.get(name)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or ast.dump(node.args, include_attributes=False) != signature:
            conflicts.append(f'{name}: function interface changed or is missing')
    return conflicts
