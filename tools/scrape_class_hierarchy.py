"""Reconstruct the Dunia engine class hierarchy from the Ghidra decompile dump.

Every gameplay class self-registers through a lazy getter of the form:

    undefined4 * FUN_<selfAddr>(void) {
      if (DAT_x == 0) {
        uVar1 = FUN_<parentAddr>();          // parent class's getter
        FUN_100016b0("CClassName", uVar1);   // register with parent
      }
      return &DAT_x;
    }

So getter-function -> class name, and the callee producing the second arg is the
parent's getter. One streaming pass recovers the full inheritance tree.

Outputs (next to this script):
  avatar_class_hierarchy.tsv   class <TAB> parent <TAB> getter_fn <TAB> dump_line
  avatar_class_hierarchy.txt   indented tree, roots first
"""
import os
import re
import sys
from collections import defaultdict

DUMP = (sys.argv[1] if len(sys.argv) > 1 else
        r"c:\Users\sambe\Downloads\Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE"
        r"\Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt")
HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRAR = "FUN_100016b0"

HDR = re.compile(r"^### (\S+)\s+@ ([0-9a-f]+)")
ASSIGN = re.compile(r"^\s*(\w+) = (FUN_[0-9a-f]+)\(\);")
REG = re.compile(r"FUN_100016b0\(\"([^\"]+)\",\s*([^)]+)\)")
# Root classes use a different inline pattern (no parent):
#   DAT_x = "CNomadObject";  ...  FUN_100ed6a0("CNomadObject",0,0);
ROOT_NAME = re.compile(r"^\s*_?DAT_\w+ = \"([^\"]+)\";")

entries = []          # (class_name, getter_fn, parent_arg, parent_getter|None, line_no)
cur_fn = None
assigns = {}
root_candidate = None

with open(DUMP, "r", encoding="utf-8", errors="replace") as f:
    for lineno, line in enumerate(f, 1):
        m = HDR.match(line)
        if m:
            cur_fn = m.group(1)
            assigns = {}
            root_candidate = None
            continue
        m = ASSIGN.match(line)
        if m:
            assigns[m.group(1)] = m.group(2)
            continue
        m = ROOT_NAME.match(line)
        if m:
            root_candidate = (m.group(1), lineno)
            continue
        if root_candidate and f'FUN_100ed6a0("{root_candidate[0]}"' in line:
            entries.append((root_candidate[0], cur_fn, "0", None, root_candidate[1]))
            root_candidate = None
            continue
        if REGISTRAR in line:
            m = REG.search(line)
            if m:
                name, arg = m.group(1), m.group(2).strip()
                parent_getter = assigns.get(arg)  # var assigned from FUN_xxx()
                if parent_getter is None and arg.startswith("FUN_"):
                    parent_getter = arg.split("(")[0]
                entries.append((name, cur_fn, arg, parent_getter, lineno))

print(f"registrations found: {len(entries)}")

# getter fn -> class name (first registration in that fn wins; the canonical
# lazy getters contain exactly one)
getter_to_name = {}
for name, fn, _arg, _pg, _ln in entries:
    if fn is not None and fn not in getter_to_name:
        getter_to_name[fn] = name

resolved = []         # (class, parent_or_root_label, fn, line)
children = defaultdict(list)
all_names = set()
for name, fn, arg, pg, ln in entries:
    if pg is not None:
        parent = getter_to_name.get(pg, f"<unresolved:{pg}>")
    elif arg in ("0", "(int)0"):
        parent = "<root>"
    else:
        parent = f"<unresolved-arg:{arg}>"
    resolved.append((name, parent, fn, ln))
    children[parent].append(name)
    all_names.add(name)

n_unres = sum(1 for _n, p, _f, _l in resolved if p.startswith("<unresolved"))
print(f"unique class names: {len(all_names)}, unresolved parents: {n_unres}")

with open(os.path.join(HERE, "avatar_class_hierarchy.tsv"), "w", encoding="utf-8") as f:
    f.write("class\tparent\tgetter_fn\tdump_line\n")
    for name, parent, fn, ln in sorted(resolved):
        f.write(f"{name}\t{parent}\t{fn}\t{ln}\n")

# tree: roots = parents that are never registered as classes themselves
roots = sorted(p for p in children if p not in all_names)
seen = set()

def walk(node, depth, out):
    out.write("  " * depth + node + "\n")
    if node in seen:                       # defensive: cycles shouldn't exist
        out.write("  " * (depth + 1) + "<cycle>\n")
        return
    seen.add(node)
    for ch in sorted(set(children.get(node, []))):
        walk(ch, depth + 1, out)

with open(os.path.join(HERE, "avatar_class_hierarchy.txt"), "w", encoding="utf-8") as f:
    for r in roots:
        f.write(f"[root: {r}]\n")
        for ch in sorted(set(children[r])):
            walk(ch, 1, f)
        f.write("\n")

print("wrote avatar_class_hierarchy.tsv / .txt")
print("roots:", ", ".join(roots[:10]))
