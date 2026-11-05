import sys, re
# Turn a check-all.sh log into "leg<TAB>PASS|FAIL|SKIP" rows, in order.
legs = []; cur = None
for line in open(sys.argv[1], errors="replace"):
    line = line.rstrip("\n")
    m = re.match(r"^(== .* ==)$", line)
    if m:
        cur = [m.group(1), "PASS"]; legs.append(cur); continue
    if cur is None: continue
    if line.startswith("** LEG FAILED"): cur[1] = "FAIL"
    elif re.match(r"^skipped \(", line) and cur[1] == "PASS": cur[1] = "SKIP"
for n, v in legs: print(f"{n}\t{v}")
