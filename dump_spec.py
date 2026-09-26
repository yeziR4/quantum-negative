import json, sys

SPEC = r"C:\Users\yezir\OneDrive\Documents\yukon-research\moth-api.json"
OUT = r"C:\Users\yezir\OneDrive\Documents\yukon-research\moth\api-notes.txt"

d = json.load(open(SPEC, encoding="utf-8"))
P = d["paths"]
S = d["components"]["schemas"]
REF = "$ref"


def brief(s):
    if not isinstance(s, dict):
        return str(s)
    if REF in s:
        return "REF:" + s[REF].split("/")[-1]
    if "anyOf" in s:
        return "anyOf[" + ",".join(brief(x) for x in s["anyOf"]) + "]"
    if "oneOf" in s:
        return "oneOf[" + ",".join(brief(x) for x in s["oneOf"]) + "]"
    t = s.get("type")
    if t == "object" or "properties" in s:
        req = set(s.get("required", []))
        ps = []
        for k, v in (s.get("properties") or {}).items():
            ps.append(("*" if k in req else "") + k + ":" + brief(v))
        extra = " addl=" + str(s.get("additionalProperties")) if "additionalProperties" in s else ""
        return "{" + ", ".join(ps) + "}" + extra
    if t == "array":
        return "array<" + brief(s.get("items", {})) + ">"
    if "enum" in s:
        return "enum" + json.dumps(s["enum"])
    out = str(t)
    if s.get("format"):
        out += " fmt=" + s["format"]
    if "default" in s:
        out += " default=" + json.dumps(s["default"])
    return out


def deref(sch):
    if isinstance(sch, dict) and REF in sch:
        return S[sch[REF].split("/")[-1]]
    return sch


L = []
for path, it in P.items():
    L.append("=" * 72)
    L.append("PATH " + path)
    for m, op in it.items():
        if m not in ("get", "post", "put", "patch", "delete"):
            continue
        L.append("  " + m.upper() + " :: " + str(op.get("summary")) + " | id=" + str(op.get("operationId")))
        desc = str(op.get("description") or "").replace("\n", " ")
        if desc:
            L.append("    desc: " + desc[:500])
        if op.get("security") is not None:
            L.append("    security: " + json.dumps(op.get("security")))
        for pr in op.get("parameters") or []:
            L.append("    param %s (%s, in=%s, req=%s): %s" % (
                pr.get("name"), brief(pr.get("schema", {})), pr.get("in"),
                pr.get("required"), str(pr.get("description"))[:200]))
        rb = op.get("requestBody")
        if rb:
            for ct, cv in (rb.get("content") or {}).items():
                sch = deref(cv.get("schema", {}))
                L.append("    REQ BODY [" + ct + "] " + brief(sch)[:2000])
        for code, cv in (op.get("responses") or {}).items():
            for ct, c2 in (cv.get("content") or {}).items():
                sch = cv and c2.get("schema", {})
                nm = sch.get(REF, "").split("/")[-1] if isinstance(sch, dict) else ""
                if nm and nm in S:
                    L.append("    RESP %s -> %s %s" % (code, nm, brief(S[nm])[:1200]))
                else:
                    L.append("    RESP %s -> %s" % (code, brief(sch)[:400]))

L.append("")
L.append("#" * 72)
L.append("FULL SCHEMA DEFINITIONS (67)")
for name, sch in sorted(S.items()):
    L.append("-" * 60)
    L.append("SCHEMA " + name + " : " + brief(sch)[:4000])

open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("written", OUT, len(L), "lines")
