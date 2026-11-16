"""Check the measured intervals against the conditional progress model."""
from collections import Counter
import json
from pathlib import Path
import re

body = Path('linked.txt').read_text().split('<fpr_fn_chooseRight>:',1)[1]
words = re.findall(r'^\s*[0-9a-f]+:\s+([0-9a-f]{8})\s',body,re.M)
assert words == 'ff010113 00112623 00812423 01010413 00058513 00040e13 ffc42083 ff842403 000e0113 00008067'.split()
rows = [tuple(int(x,16) for x in row) for row in re.findall(
    r'W ([a-f0-9]{8}) ([a-f0-9]{8}) ([a-f0-9]{8})',Path('board.log').read_text())]
assert len(rows)==2160 and all(n==12 for _,n,_ in rows) and 'exit 42' in Path('board.log').read_text()
def ceiling(steps):
    advancing = steps*32
    # One blocking read per advance, one carried read, and up to eleven writes
    # or other carry-in transactions, each charged independently.
    return advancing+20*(advancing+1+11)
result={'conditional_leaf_cycles':ceiling(10),'conditional_window_cycles':ceiling(14),'modes':{}}
for i,key in enumerate(('baseline','conflict','stores','both')):
    samples=rows[i::4]
    hist=Counter(c for c,_,_ in samples)
    assert max(hist)<=ceiling(14)
    result['modes'][key]={'trials':len(samples),'histogram':dict(sorted(hist.items())),
                          'distinct_start_low32_mod_540':len({s%540 for _,_,s in samples})}
print(json.dumps(result,indent=2))
