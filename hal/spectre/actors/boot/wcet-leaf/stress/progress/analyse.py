"""Account for A2 port traffic, including speculative fetch and earlier writes."""
from collections import Counter
from pathlib import Path
import json

def summarise(files):
    maxima = Counter()
    total = retries = 0
    for path in files:
        # Unknown initial tags. For each set remember only one guaranteed line.
        # Discard it even on a store hit. A different read in the same set can
        # replace it; consecutive reads of the same line need only one fill.
        known, lines, reads = {}, set(), set()
        fills = 0
        for row in path.read_text().splitlines():
            fields = row.split()
            if not fields: continue
            if fields[0] == 'P':
                word, store = int(fields[2], 16), int(fields[3])
                line = word >> 2
                index = line & 2047
                lines.add(line)
                if store:
                    known.pop(index,None)
                else:
                    reads.add(line)
                    if known.get(index) != line:
                        fills += 1
                    known[index] = line
            elif fields[0] == 'W':
                n, advancing, gap, refills, clocks, pushes, carry, retry = map(int,fields[1:])
                # One extra carry-in transaction in addition to the four
                # queued writes; covers a refill already active on entry.
                retries += retry
                transfer_cap = fills + pushes + 5
                envelope = advancing + 20*transfer_cap
                assert refills <= fills+1 and clocks <= envelope, (path,n)
                for key,val in dict(advance=advancing,gap=gap,read_lines=len(reads),
                        all_lines=len(lines),charged_fills=fills,refills=refills,
                        pushes=pushes,transfer_cap=transfer_cap,window=envelope,
                        physical_sim=clocks).items():
                    maxima[key] = max(maxima[key],val)
                known,lines,reads = {},set(),set()
                fills=0
                total+=1
    maxima['windows']=total
    maxima['counter_retry_clocks']=retries
    return dict(sorted(maxima.items()))

files = sorted(Path('runs').glob('*.log'))
assert len(files)==100
result={key:summarise(group) for key,group in [
    ('natural',[p for p in files if p.name.endswith('-0-0-None.log')]),('all',files)]}
assert result['all']['windows']==25600
print(json.dumps(result,indent=2))
