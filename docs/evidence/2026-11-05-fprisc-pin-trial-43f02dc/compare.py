import sys, re
# compare.py name=tsv ...  -> one row per leg that is not PASS everywhere
def norm(n): return re.sub(r"/Users/[^/]+/Documents/GitHub/[^/ ,)]+", "<tree>", n)
cols = []; order = []
for a in sys.argv[1:]:
    name, path = a.split("=", 1); d = {}
    for line in open(path):
        if "\t" not in line or line.startswith("SWEEP"): continue
        leg, v = line.rstrip("\n").split("\t"); leg = norm(leg); d[leg] = v
        if leg not in order: order.append(leg)
    cols.append((name, d))
print("leg\t" + "\t".join(n for n, _ in cols))
for leg in order:
    vs = [d.get(leg, "-") for _, d in cols]
    if any(v != "PASS" for v in vs): print(leg + "\t" + "\t".join(vs))
