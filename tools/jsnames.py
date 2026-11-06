"""jsnames.py — the names a JavaScript file reads that nothing declares (wavelenscat.py --check; review 2026-11-05 runs A-09).

The page is one scope put together from wavelens/src/*.js, the extension two node files and a webview script; there is no
eslint in the repository (no npm). This reads the tokens (comments, strings, templates with their ${…}, regular expressions
told from a division by the token before), the names declared anywhere in the file (function, class, var / let / const with
their patterns, the parameters of functions, methods, arrows and catch) and the names read (not after a dot, not an object's
key, not a method's name): a name read that is declared nowhere and is no global of the browser / node is a misspelling (or
a global to add to BROWSER / NODE). Scopes are not followed: a name declared in one function and read in another passes.
"""
import re

KEYWORDS = set('''break case catch class const continue debugger default delete do else export extends finally for function if
import in instanceof let new return super switch this throw try typeof var void while with yield await async of get set static
true false null undefined NaN Infinity arguments'''.split())
REGEX_AFTER = set('return typeof case in of new delete void throw instanceof do else yield await'.split())
IDENT = re.compile(r'[A-Za-z_$][\w$]*')
NUM = re.compile(r'0[xXbBoO][\da-fA-F_]+n?|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?n?')
PUNCT = re.compile(r'>>>=|\.\.\.|===|!==|\*\*=|<<=|>>=|>>>|\?\?=|&&=|\|\|=|=>|==|!=|<=|>=|&&|\|\||\?\?|\?\.|\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|\*\*|<<|>>|[{}()\[\];,<>+\-*/%&|^!~?:=.@#]')


def tokens(text):
    """[(kind, value, line)]: kind 'id', 'num', 'str', 'tmpl', 're', 'p' (a punctuator); comments left out. A template's
    ${…} is code: its tokens come between the template's parts."""
    out, i, n, line = [], 0, len(text), 1
    stack = []   # one brace depth per template ${ … } open
    def prev():
        return out[-1] if out else None
    def regex_ok():
        p = prev()
        if p is None:
            return True
        k, v = p[0], p[1]
        if k == 'tmpl':
            return v == '${'
        if k in ('num', 'str', 're'):
            return False
        if k == 'id':
            return v in REGEX_AFTER
        return v not in (')', ']', '}')
    def template(i):   # i after the backquote (or after a ${ … }'s closing brace): -> the index after the part
        nonlocal line
        while i < n:
            c = text[i]
            if c == '\\':
                i += 2
                continue
            if c == '\n':
                line += 1
            if c == '`':
                return i + 1, False
            if c == '$' and text.startswith('${', i):
                return i + 2, True
            i += 1
        return i, False
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
            continue
        if c in ' \t\r':
            i += 1
            continue
        if text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            line += text.count('\n', i, j)
            i = j
            continue
        if c in '\'"':
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == '\\' else 1
            out.append(('str', text[i:j + 1], line))
            i = j + 1
            continue
        if c == '`':
            j, code = template(i + 1)
            out.append(('tmpl', '${' if code else '`', line))
            if code:
                stack.append(0)
            i = j
            continue
        if c == '}' and stack:
            if stack[-1] == 0:
                stack.pop()
                j, code = template(i + 1)
                out.append(('tmpl', '${' if code else '`', line))
                if code:
                    stack.append(0)
                i = j
                continue
            stack[-1] -= 1
        if c == '{' and stack:
            stack[-1] += 1
        if c == '/' and regex_ok():
            j, cls = i + 1, False
            while j < n and (cls or text[j] != '/'):
                if text[j] == '\\':
                    j += 1
                elif text[j] == '[':
                    cls = True
                elif text[j] == ']':
                    cls = False
                elif text[j] == '\n':
                    break
                j += 1
            j += 1
            while j < n and (text[j].isalnum()):
                j += 1
            out.append(('re', text[i:j], line))
            i = j
            continue
        m = IDENT.match(text, i)
        if m:
            out.append(('id', m.group(), line))
            i = m.end()
            continue
        m = NUM.match(text, i)
        if m and m.end() > i:
            out.append(('num', m.group(), line))
            i = m.end()
            continue
        m = PUNCT.match(text, i)
        if m:
            out.append(('p', m.group(), line))
            i = m.end()
            continue
        i += 1   # anything else (a non-ASCII letter in a name: none in the sources)
    return out


def close(toks, i):
    """The index of the bracket closing the one at i."""
    pairs = {'(': ')', '[': ']', '{': '}'}
    o, c, d = toks[i][1], pairs[toks[i][1]], 0
    for j in range(i, len(toks)):
        if toks[j][0] == 'p':
            if toks[j][1] == o:
                d += 1
            elif toks[j][1] == c:
                d -= 1
                if d == 0:
                    return j
    return len(toks) - 1


def names(text):
    """(declared, used): the names declared anywhere (function, class, var / let / const and their patterns, parameters of
    functions, methods, arrows, catch) and [(name, line)] of every name read (not after a dot, not a key)."""
    toks = tokens(text)
    declared, used = set(), []
    def ids(a, b):   # the names of a parameter list, without its defaults' expressions
        out, d, skip = set(), 0, False
        for t in toks[a:b]:
            if t[0] == 'p' and t[1] in '([{':
                d += 1
            elif t[0] == 'p' and t[1] in ')]}':
                d -= 1
            elif t[0] == 'p' and t[1] == '=' and d == 0:
                skip = True
            elif t[0] == 'p' and t[1] == ',' and d == 0:
                skip = False
            elif t[0] == 'id' and not skip:
                out.add(t[1])
        return out
    is_p = lambda k, v: 0 <= k < len(toks) and toks[k][0] == 'p' and toks[k][1] == v
    for k, (kind, v, line) in enumerate(toks):
        if kind == 'p' and v == '(':
            j = close(toks, k)
            before = toks[k - 1] if k else None
            if is_p(j + 1, '=>') or is_p(j + 1, '{') and not (before and before[0] == 'id' and before[1] in ('if', 'while', 'for', 'switch', 'with')):
                declared |= ids(k + 1, j)   # parameters (of an arrow, a function, a method; catch's)
            elif before and before[1] == 'catch':
                declared |= ids(k + 1, j)
            continue
        if kind != 'id':
            continue
        nxt = toks[k + 1] if k + 1 < len(toks) else ('p', '', line)
        prv = toks[k - 1] if k else ('p', '', line)
        if v in ('function', 'class') and nxt[0] == 'id':
            declared.add(nxt[1])
        if v == 'function' and is_p(k + 1, '*') and k + 2 < len(toks):
            declared.add(toks[k + 2][1])
        if v in ('var', 'let', 'const'):
            in_for = is_p(k - 1, '(') and k > 1 and toks[k - 2][1] == 'for'
            # the bindings up to the declaration's end: names before "=" at depth 0, all names of a pattern
            j, d = k + 1, 0
            while j < len(toks):
                t = toks[j]
                if t[0] == 'p' and t[1] in '([{':
                    d += 1
                elif t[0] == 'p' and t[1] in ')]}':
                    if d == 0:
                        break
                    d -= 1
                elif t[0] == 'p' and t[1] == ';' and d == 0:
                    break
                elif t[0] == 'p' and t[1] == '=' and d == 0:
                    # skip the initializer to the next "," at depth 0 (or the end)
                    e, dd = j + 1, 0
                    while e < len(toks):
                        u = toks[e]
                        if u[0] == 'p' and u[1] in '([{':
                            dd += 1
                        elif u[0] == 'p' and u[1] in ')]}':
                            if dd == 0:
                                break
                            dd -= 1
                        elif u[0] == 'p' and u[1] in (',', ';') and dd == 0:
                            break
                        elif dd == 0 and u[0] == 'id' and u[1] in ('var', 'let', 'const', 'function', 'class', 'return', 'if', 'for'):
                            break
                        if dd == 0 and e > j + 1 and toks[e - 1][2] != u[2] and u[0] == 'id' and toks[e - 1][0] in ('id', 'str', 'num') :
                            break   # no semicolon: a new statement on the next line
                        e += 1
                    j = e
                    if j < len(toks) and is_p(j, ','):
                        j += 1
                        continue
                    break
                elif t[0] == 'id' and t[1] in ('of', 'in') and d == 0 and in_for:
                    break
                elif t[0] == 'id':
                    declared.add(t[1])
                j += 1
        if v in KEYWORDS:
            continue
        if prv[0] == 'p' and prv[1] in ('.', '?.'):
            continue
        if prv[0] == 'p' and prv[1] == '#':
            continue
        if nxt[0] == 'p' and nxt[1] == ':' and prv[0] == 'p' and prv[1] in ('{', ','):
            continue   # a key of an object literal
        if nxt[0] == 'p' and nxt[1] == '(' and (prv[0] == 'p' and prv[1] in ('{', '}', ',', ';') or prv[0] == 'id' and prv[1] in ('get', 'set', 'static', 'async')):
            j = close(toks, k + 1)
            if is_p(j + 1, '{'):
                continue   # a method's name
        if nxt[0] == 'p' and nxt[1] == '=>':
            declared.add(v)   # the one parameter of an arrow
        used.append((v, line))
    return declared, used


BROWSER = set('''AbortController Array ArrayBuffer BigInt Blob Boolean CSS ClipboardItem CustomEvent DOMParser DataTransfer DataView
Date DecompressionStream Error Event EventSource EventTarget File Float64Array Function HTMLAnchorElement HTMLInputElement Image
Int32Array Intl JSON KeyboardEvent Map Math MessageEvent MouseEvent MutationObserver Node Number Object Promise RegExp ResizeObserver
Response Set String TextDecoder TextEncoder TypeError URL Uint8Array WeakMap WeakRef WebAssembly Worker atob btoa
cancelAnimationFrame clearInterval clearTimeout console decodeURIComponent document encodeURIComponent fetch getComputedStyle
getSelection indexedDB innerHeight innerWidth isFinite isNaN localStorage location matchMedia navigator parseFloat parseInt
performance queueMicrotask requestAnimationFrame self setInterval setTimeout structuredClone window'''.split())
# the page's own globals of other scripts: mkhtml.py's WAVES, the VS Code webview's API and the viewer host.js waits for
PAGE = {'WAVES', 'WaveLens', 'acquireVsCodeApi'}
NODE = set('''Array BigInt Boolean Buffer Date Error JSON Map Math Object Promise RegExp Set String URL Uint8Array clearInterval clearTimeout
console encodeURIComponent decodeURIComponent isFinite isNaN module parseFloat parseInt process require setInterval setTimeout
window'''.split())   # window: links.js reads it where there is one


def undeclared(text, known):
    """[(name, line)] of the first read of every name declared nowhere in text and not in known."""
    declared, used, out = *names(text), {}
    for v, line in used:
        if v not in declared and v not in known:
            out.setdefault(v, line)
    return sorted(out.items(), key=lambda x: x[1])
