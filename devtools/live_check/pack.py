"""Pack report_builder modules (docstrings/comments stripped) into gzip+base64 for injection into the live-check worker."""
import ast, gzip, base64, json, sys, pathlib

def strip(src: str) -> str:
    t = ast.parse(src)
    for n in ast.walk(t):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(getattr(b[0], "value", None), ast.Constant) and isinstance(b[0].value.value, str):
                n.body = b[1:] or [ast.Pass()]
    return ast.unparse(t)

def pack(names, root="src/report_builder"):
    d = {n: strip(pathlib.Path(root, n + ".py").read_text()) for n in names}
    j = json.dumps(d, ensure_ascii=False).encode()
    return base64.b64encode(gzip.compress(j, 9)).decode(), len(j)

if __name__ == "__main__":
    out = sys.argv[1]
    names = sys.argv[2:]
    b, n = pack(names)
    pathlib.Path(out).write_text(b)
    print(n, len(b))
