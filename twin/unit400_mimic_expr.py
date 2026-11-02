"""MIMIC -> Python expression translator (tokenizer-based, v3)."""
import re


MIMIC_BUILTINS = {
    "MIN": "min", "MAX": "max", "ABS": "abs",
    "SQRT": "math.sqrt", "EXP": "math.exp",
    "LN": "math.log", "LOG": "math.log10",
    "SIN": "math.sin", "COS": "math.cos", "TAN": "math.tan",
    "INT": "int", "ROUND": "round",
    "TRUE": "True", "FALSE": "False",
}


def strip_comments(expr):
    expr = re.sub(r"/\*.*?\*/", " ", expr, flags=re.DOTALL)
    expr = re.sub(r"//[^\n]*", "", expr)
    return expr


def decode_html_entities(s):
    return (s.replace("&gt;", ">")
             .replace("&lt;", "<")
             .replace("&amp;", "&")
             .replace("&quot;", '"')
             .replace("&apos;", "'"))


T_ID, T_NUM, T_STR, T_OP, T_WS = "ID", "NUM", "STR", "OP", "WS"


def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            tokens.append((T_WS, text[i:j]))
            i = j
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 1
            if j < n:
                j += 1
            tokens.append((T_STR, text[i:j]))
            i = j
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i+1].isdigit()):
            j = i
            while j < n and (text[j].isdigit() or text[j] == "."):
                j += 1
            tokens.append((T_NUM, text[i:j]))
            i = j
            continue
        if c.isalpha() or c in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            tokens.append((T_ID, text[i:j]))
            i = j
            continue
        for op in ("<=", ">=", "<>", "!=", ":=", "==", "&&", "||"):
            if text[i:i+len(op)] == op:
                tokens.append((T_OP, op))
                i += len(op)
                break
        else:
            tokens.append((T_OP, c))
            i += 1
    return tokens


def _match_out(name):
    m = re.match(r"^[Oo][Uu][Tt]_(\d+)$", name)
    return int(m.group(1)) if m else None

def _match_in(name):
    m = re.match(r"^[Ii][Nn]_(\d+)$", name)
    return int(m.group(1)) if m else None

def _match_f(name):
    m = re.match(r"^[Ff]\$(\d+)$", name)
    return int(m.group(1)) if m else None


def _skip_ws(tokens, j):
    n = len(tokens)
    while j < n and tokens[j][0] == T_WS:
        j += 1
    return j


def emit_expr(tokens):
    """Emit Python source for a token list (no IF/THEN/ELSE/ENDIF expected)."""
    out = []
    n = len(tokens)

    # First pass: identify assignment targets (tokens preceding ':=')
    targets = set()
    j = 0
    while j < n:
        if tokens[j][0] == T_OP and tokens[j][1] == ":=":
            k = j - 1
            while k >= 0 and tokens[k][0] == T_WS:
                k -= 1
            if k >= 0:
                targets.add(k)
        j += 1

    i = 0
    while i < n:
        typ, val = tokens[i]

        if typ == T_WS:
            out.append(" ")
            i += 1
            continue
        if typ == T_STR:
            out.append(val)
            i += 1
            continue
        if typ == T_NUM:
            out.append(val)
            i += 1
            continue

        if typ == T_OP:
            if val == ":=":
                out.append("=")
            elif val == "<>":
                out.append("!=")
            elif val == "&&":
                out.append(" and ")
            elif val == "||":
                out.append(" or ")
            elif val == "=":
                out.append("==")
            else:
                out.append(val)
            i += 1
            continue

        if typ == T_ID:
            upper = val.upper()

            # Handle VAL("...") — skip '(' string ')'
            if upper == "VAL":
                j = _skip_ws(tokens, i + 1)
                if j < n and tokens[j][0] == T_OP and tokens[j][1] == "(":
                    j = _skip_ws(tokens, j + 1)
                    if j < n and tokens[j][0] == T_STR:
                        path = tokens[j][1][1:-1]
                        j = _skip_ws(tokens, j + 1)
                        if j < n and tokens[j][0] == T_OP and tokens[j][1] == ")":
                            j += 1
                        out.append('self._read("%s")' % path)
                        i = j
                        continue
                # fallback
                out.append("VAL")
                i += 1
                continue

            # Handle CONST("...") — same pattern
            if upper == "CONST":
                j = _skip_ws(tokens, i + 1)
                if j < n and tokens[j][0] == T_OP and tokens[j][1] == "(":
                    j = _skip_ws(tokens, j + 1)
                    if j < n and tokens[j][0] == T_STR:
                        name = tokens[j][1][1:-1]
                        j = _skip_ws(tokens, j + 1)
                        if j < n and tokens[j][0] == T_OP and tokens[j][1] == ")":
                            j += 1
                        out.append('self._const("%s")' % name)
                        i = j
                        continue
                out.append("CONST")
                i += 1
                continue

            # MIMIC builtins (MIN, MAX, ...) — pure name substitution
            if upper in MIMIC_BUILTINS:
                out.append(MIMIC_BUILTINS[upper])
                i += 1
                continue

            # IF/THEN/ELSE/ENDIF should not appear here
            if upper in ("IF", "THEN", "ELSE", "ENDIF"):
                i += 1
                continue

            # OUT_N
            on = _match_out(val)
            if on is not None:
                if i in targets:
                    out.append('self.outputs["OUT_%d"]' % on)
                else:
                    out.append('self.outputs.get("OUT_%d", 0.0)' % on)
                i += 1
                continue

            # IN_N
            ino = _match_in(val)
            if ino is not None:
                out.append('self.inputs.get("IN_%d", 0.0)' % ino)
                i += 1
                continue

            # F$N
            fn = _match_f(val)
            if fn is not None:
                if i in targets:
                    out.append('self.L[%d]' % fn)
                else:
                    out.append('self.L.get(%d, 0.0)' % fn)
                i += 1
                continue

            out.append(val)
            i += 1
            continue

    return "".join(out)


def split_statements(tokens):
    """Break a token stream into logical statements."""
    statements = []
    current = []
    i, n = 0, len(tokens)
    while i < n:
        typ, val = tokens[i]
        if typ == T_ID:
            upper = val.upper()
            if upper == "THEN":
                statements.append(("if", current))
                current = []
                i += 1
                continue
            if upper == "ELSE":
                if current:
                    statements.append(("stmt", current))
                    current = []
                statements.append(("else", []))
                i += 1
                continue
            if upper == "ENDIF":
                if current:
                    statements.append(("stmt", current))
                    current = []
                statements.append(("endif", []))
                i += 1
                continue
        if typ == T_OP and val == ";":
            if current:
                statements.append(("stmt", current))
                current = []
            i += 1
            continue
        current.append((typ, val))
        i += 1
    if current:
        statements.append(("stmt", current))
    return statements


def _strip_keyword(tokens, keyword):
    """Remove a leading keyword (IF, etc.) plus whitespace, return rest."""
    i = 0
    while i < len(tokens) and tokens[i][0] == T_WS:
        i += 1
    if i < len(tokens) and tokens[i][0] == T_ID and tokens[i][1].upper() == keyword:
        i += 1
    return tokens[i:]


def translate_to_lines(expr):
    expr = strip_comments(expr)
    expr = decode_html_entities(expr)
    tokens = tokenize(expr)
    stmts = split_statements(tokens)

    lines = []
    indent = 0
    for kind, stmt_tokens in stmts:
        if kind == "if":
            cond_tokens = _strip_keyword(stmt_tokens, "IF")
            cond_py = emit_expr(cond_tokens).strip()
            lines.append("    " * indent + "if %s:" % cond_py)
            indent += 1
        elif kind == "else":
            indent = max(0, indent - 1)
            lines.append("    " * indent + "else:")
            indent += 1
        elif kind == "endif":
            indent = max(0, indent - 1)
        elif kind == "stmt":
            py = emit_expr(stmt_tokens).strip()
            if py:
                lines.append("    " * indent + py)
    return lines


def generate_calc_class(module, tag, expression):
    lines = translate_to_lines(expression)
    cls_name = "Calc_%s_%s" % (module, tag)
    cls_name = cls_name.replace("-", "_").replace(".", "_")
    if not lines:
        body = "        pass"
    else:
        body = "\n".join("        " + ln for ln in lines)
    return "\n\nclass %s(CalcObject):\n    def evaluate(self):\n%s\n" % (cls_name, body)
