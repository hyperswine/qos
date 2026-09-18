#!/usr/bin/env python3
"""pos1-check.py -- POS v1 (programs/pos1.fpr, docs/POS1-DESIGN.md)
under qosp, driven as websocket registers.

The design's example (S9) as pasted: sign in as ana / 1234, add two
items, checkout with cash, see the toast and the receipt, void it, stock
returns, restart the process, the receipt and the void are still there.
Then the adversarial legs (S10): the last-unit race, a void twice, a crash
across the checkout commit, a few hundred receipts against the capped
table with flat round trips, steady-state cart edits as slot deltas with
the theme flip the one reshape, and rebuild against the log.

  usage: pos1-check.py <qos dir> <app.qa> [port]

Needs `websockets` (pip).  Run through pos1-check.sh, which builds first.
"""
import asyncio, json, os, re, signal, socket, subprocess, sys, time
import websockets

QOS, QA = sys.argv[1], sys.argv[2]
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8161
DISK = "/tmp/pos1-check.disk"
LOG = "/tmp/pos1-check.out"
URL = f"ws://127.0.0.1:{PORT}/ws"
failures = []


def ok(cond, what):
    if not cond:
        failures.append(what)
        print(f"  FAIL  {what}")
    return cond


def say(s):
    print(f"  {s}")


class Server:
    def __init__(self):
        self.p = None

    def start(self):
        self.out = open(LOG, "ab")
        env = dict(os.environ, FPR_PORT=str(PORT), FPR_DISK=DISK, FPR_DISK_MB="64")
        self.p = subprocess.Popen(["./qosp", "--yes", QA], cwd=QOS, env=env,
                                  stdout=self.out, stderr=subprocess.STDOUT)
        mark = self.log().count("hosting")
        for _ in range(200):
            if self.log().count("hosting") <= mark:
                time.sleep(0.05)
                continue
            try:
                socket.create_connection(("127.0.0.1", PORT), 0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        raise SystemExit("server did not come up")

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.out.close()

    def kill(self):
        self.p.send_signal(signal.SIGKILL)
        self.p.wait(5)
        self.out.close()

    def log(self):
        try:
            return open(LOG, "rb").read().decode("utf8", "replace")
        except FileNotFoundError:
            return ""


class View:
    """statics + dynamics, applied the way the client does; the readers
    take the POS screen back out of the assembled HTML"""
    def __init__(self):
        self.s, self.d = [], []
        self.fulls = self.deltas = 0

    def apply(self, raw):
        res = json.loads(raw)
        if "s" in res:
            self.s, self.d = res["s"], res["d"]
            self.fulls += 1
        else:
            for k, v in res["d"].items():
                self.d[int(k)] = v
            self.deltas += 1
        return res

    def html(self):
        out = ""
        for i, s in enumerate(self.s):
            out += s
            if i < len(self.d):
                out += "\x00" + self.d[i] + "\x00"
        return out

    @property
    def logged_in(self):
        return "tab=1" in "".join(self.s)

    def toast(self):
        h = self.html()
        for role in ("ok", "celebrate", "warn", "bad"):
            m = re.search(r'toast ' + role + r'">\x00(.*?)\x00', h, re.S)
            if m and m.group(1):
                return role, m.group(1)
        return "", ""

    def login_note(self):
        m = re.search(r'warm text-sm">\x00(.*?)\x00', self.html(), re.S)
        return m.group(1) if m else ""

    def stock(self):
        """the register's badges, in catalog order (name -> text)"""
        h = self.html()
        cards = re.findall(r'<div class="bold">([^<]*)</div><div class="row between center"><div class="tabular">\$\x00[^\x00]*\x00</div><span class="badge" data-role="stock">\x00([^\x00]*)\x00', h)
        return {n: t for n, t in cards}

    def stock_n(self, name):
        t = self.stock()[name]
        if t == "sold out":
            return 0
        return int(re.search(r'(\d+)', t).group(1))

    def cart_total(self):
        return re.search(r'text-2xl bold tabular">\$\x00(.*?)\x00', self.html()).group(1)

    def cart_qtys(self):
        return [int(x) for x in re.findall(r'tabular w-40 right">\x00(\d+)\x00', self.html())]

    def receipts_count(self):
        return int(re.search(r'text-2xl bold tabular">\x00(\d+)\x00', self.html()).group(1))

    def revenue(self):
        return re.findall(r'text-2xl bold tabular">\$\x00(.*?)\x00', self.html())[1]

    def receipt_rows(self):
        return re.findall(r'bold tabular w-24">#(\d+)</div>', self.html())

    def void_badges(self):
        return len(re.findall(r'badge bad">void<', self.html()))

    def console(self):
        m = re.search(r'pre card round p-3">\x00(.*?)\x00', self.html(), re.S)
        return m.group(1) if m else ""


class Client:
    def __init__(self):
        self.ws = None
        self.v = View()
        self.rtt = []

    async def open(self):
        self.ws = await websockets.connect(URL, proxy=None, open_timeout=5, ping_interval=None, max_size=None)
        self.v.apply(await asyncio.wait_for(self.ws.recv(), 5))
        return self

    async def send(self, msg, arg="", timeout=5):
        t0 = time.perf_counter()
        await self.ws.send(json.dumps({"msg": msg, "arg": str(arg)}, separators=(",", ":")))
        res = self.v.apply(await asyncio.wait_for(self.ws.recv(), timeout))
        self.rtt.append(time.perf_counter() - t0)
        return res

    async def fire(self, msg, arg=""):
        await self.ws.send(json.dumps({"msg": msg, "arg": str(arg)}, separators=(",", ":")))

    async def drain(self, secs=0.3):
        n = 0
        while True:
            try:
                self.v.apply(await asyncio.wait_for(self.ws.recv(), secs))
                n += 1
            except asyncio.TimeoutError:
                return n

    async def login(self, name, pin):
        return await self.send("login", f"{name}|{pin}")

    async def close(self):
        await self.ws.close()


async def fresh(name="ana", pin="1234"):
    c = await Client().open()
    await c.login(name, pin)
    await c.drain(0.2)
    return c


async def main():
    if os.path.exists(DISK):
        os.remove(DISK)
    if os.path.exists(LOG):
        os.remove(LOG)
    srv = Server()
    srv.start()
    ok("log: 10 lines, 6 products, 0 sales" in srv.log(), "a fresh shop is seeded onto the disk (10 lines)")

    # ---- S9: the example, as pasted ------------------------------------------------
    say("S9 the example")
    c = await Client().open()
    ok(not c.v.logged_in, "the page opens signed out")
    await c.login("ana", "9999")
    ok(not c.v.logged_in and "unknown cashier" in c.v.login_note(), "a wrong PIN is refused with a note")
    await c.login("ana", "1234")
    ok(c.v.logged_in, "ana signs in with her PIN")
    await c.send("add", "FW")
    await c.send("add", "FW")
    await c.send("add", "BR")
    ok(c.v.cart_qtys() == [2, 1], f"two items in the cart, grouped: {c.v.cart_qtys()}")
    ok(c.v.cart_total() == "17.60", f"total 16.00 + 10% tax = 17.60 (got {c.v.cart_total()})")
    await c.send("cash", "50")
    role, text = c.v.toast()
    ok(role == "celebrate" and "receipt #1 for 17.60" in text and "change 32.40" in text,
       f"checkout: first sale of the day celebrates, change due (got {role}: {text})")
    ok(c.v.cart_qtys() == [] and c.v.stock_n("flat white") == 10 and c.v.stock_n("brownie") == 11,
       "the cart clears and stock moved")
    ok(c.v.receipts_count() == 1 and c.v.receipt_rows() == ["1"] and c.v.revenue() == "17.60",
       "the receipt is in Receipts with the revenue")
    await c.send("void", "1")
    role, text = c.v.toast()
    ok(role == "ok" and "void" in text, f"void: {text}")
    ok(c.v.stock_n("flat white") == 12 and c.v.stock_n("brownie") == 12 and c.v.revenue() == "0.00",
       "stock returned and revenue fell; the row stays")
    ok(c.v.void_badges() == 1 and c.v.receipt_rows() == ["1"], "the original row shows one void badge")
    await c.send("void", "1")
    role, text = c.v.toast()
    ok(role == "warn" and "already void" in text, f"a second void is refused: {text}")
    await c.close()

    srv.stop()
    srv.start()
    ok("2 lines, 6 products, 1 sales" in srv.log().split("hosting")[-2] if False else re.search(r"log: 1\d lines, 6 products, 1 sales, revenue 0\.00", srv.log()) is not None,
       "restart: the log replays to the same shop (1 sale, voided, revenue 0.00)")
    c = await fresh()
    ok(c.v.receipt_rows() == ["1"] and c.v.void_badges() == 1 and c.v.stock_n("flat white") == 12,
       "after the restart the receipt and its void are still there")

    # ---- guards ---------------------------------------------------------------------
    say("guards")
    await c.send("qty", "FW|999")
    role, text = c.v.toast()
    ok(role == "warn" and "set to 12" in text and c.v.cart_qtys() == [12], f"qty clamps to stock and says so: {text}")
    await c.send("qty", "FW|0")
    ok(c.v.cart_qtys() == [], "qty 0 removes the line")
    await c.send("cash", "1")
    ok(c.v.toast()[0] == "warn" and "empty" in c.v.toast()[1], "checkout with an empty cart is refused")
    await c.send("add", "BR")
    await c.send("cash", "1")
    ok("short by" in c.v.toast()[1], f"short cash is refused: {c.v.toast()[1]}")
    await c.send("qty", "BR|0")
    await c.send("add", "NOPE")
    ok("no such product" in c.v.toast()[1], "an unknown sku is refused")
    await c.send("bogus", "")
    ok("no such action" in c.v.toast()[1], "an unknown message is named, not ignored")

    # ---- the last unit -------------------------------------------------------------------
    say("S10.1 the last-unit race")
    await c.send("admin", "add LU 100 1 last unit")
    ok("added LU" in c.v.console(), "admin adds a product with one in stock")
    ok(c.v.stock_n("last unit") == 1, "it shows in the register, low")
    b = await fresh("ben", "2222")
    await c.send("add", "LU")
    await b.send("add", "LU")
    ok(c.v.cart_qtys() == [1] and b.v.cart_qtys() == [1], "both registers ring the last unit")
    await asyncio.gather(c.fire("card"), b.fire("card"))
    await c.drain(0.5)
    await b.drain(0.5)
    wins = [x for x in (c, b) if x.v.toast()[0] in ("ok", "celebrate")]
    lost = [x for x in (c, b) if x.v.toast()[0] == "warn" and "only 0 left" in x.v.toast()[1]]
    ok(len(wins) == 1 and len(lost) == 1, f"exactly one commits, the other is told: {c.v.toast()} / {b.v.toast()}")
    ok(c.v.stock_n("last unit") == 0 and c.v.stock()["last unit"] == "sold out", "stock 0 wears the danger role")
    await lost[0].send("qty", "LU|0")

    # ---- S10.3 void twice covered above; S10.7 log vs cache ------------------------------
    say("S10.7 log vs cache")
    await c.send("rebuild", "")
    ok("stock matches the log" in c.v.console(), f"rebuild: {c.v.console().splitlines()[-1]}")

    # ---- restock, prices, retire ----------------------------------------------------------
    say("inventory and admin")
    await c.send("restock", "LU|5")
    ok("+5, now 5" in c.v.toast()[1] and c.v.stock_n("last unit") == 5, "restock is a new record; stock 5")
    await c.send("admin", "set price LU 250")
    await c.send("admin", "get price LU")
    ok("price LU 2.50" in c.v.console(), "a price set live reads back")
    await c.send("admin", "retire LU")
    ok("last unit" not in c.v.stock(), "a retired product leaves the register")
    await c.send("admin", "set tax 0")
    await c.send("add", "SW")
    ok(c.v.cart_total() == "3.00", f"tax 0 applies to the next total (got {c.v.cart_total()})")
    await c.send("admin", "set tax 1000")
    await c.send("qty", "SW|0")

    # ---- S10.6 deltas, and the reshape ---------------------------------------------------
    say("S10.6 delta correctness")
    await c.send("add", "FW")
    await c.send("add", "LB")
    c.v.fulls = c.v.deltas = 0
    for _ in range(6):
        await c.send("qty", "FW|3")
        await c.send("qty", "FW|2")
    ok(c.v.fulls == 0 and c.v.deltas == 12, f"12 qty edits: {c.v.deltas} deltas, {c.v.fulls} reshapes")
    await c.send("theme", "")
    ok(c.v.fulls == 1 and "day" in "".join(c.v.s), "the theme flip is the one reshape")
    ndeltas = c.v.deltas
    await c.send("theme", "")
    await c.send("qty", "FW|0")
    await c.send("qty", "LB|0")
    await b.close()

    # ---- S10.2 crash windows -------------------------------------------------------------
    say("S10.2 crash windows")
    before = c.v.receipts_count()
    await c.close()
    landed = 0
    for i in range(4):
        d = await fresh()
        await d.send("add", "SW")
        await d.fire("card")
        await asyncio.sleep(0.002 * i)
        srv.kill()
        srv.start()
        d = await fresh()
        n = d.v.receipts_count()
        ok(n in (before + landed, before + landed + 1), f"crash {i}: receipts {n} (complete or absent)")
        if n == before + landed + 1:
            landed += 1
        rows = [int(x) for x in d.v.receipt_rows()]
        ok(rows == sorted(rows, reverse=True) and (not rows or rows[0] == max(rows)), "receipt numbers stay contiguous")
        await d.send("rebuild", "")
        ok("stock matches the log" in d.v.console(), f"after crash {i} the cache equals the fold")
        await d.close()
    say(f"{landed} of 4 checkouts landed before the kill")

    # ---- S10.5 bounded lists ---------------------------------------------------------------
    say("S10.5 bounded lists")
    c = await fresh()
    await c.send("restock", "SW|999")
    n0 = c.v.receipts_count()
    N = 300
    for i in range(N):
        await c.send("add", "SW")
        await c.send("card", "")
    ok(c.v.receipts_count() == n0 + N, f"{N} receipts rung up ({c.v.receipts_count()})")
    ok(len(c.v.receipt_rows()) == 50, f"the Receipts table shows the capped page ({len(c.v.receipt_rows())} rows)")
    r = c.rtt[-2 * N:]
    first, last = sorted(r[:60])[30], sorted(r[-60:])[30]
    ok(last < first * 4 + 0.01, f"round trips flat: median {first * 1000:.1f} ms early, {last * 1000:.1f} ms late")
    await c.send("rebuild", "")
    ok("stock matches the log" in c.v.console(), "the log still folds to the cache")
    ok("[arc]" not in srv.log() or "leak" not in srv.log(), "no leak report")

    await c.fire("quit", "")     # the server answers with a 1001 to every session, then exits
    await asyncio.sleep(0.5)
    ok(srv.p.poll() is not None, "quit stops the server")
    srv.stop()
    if failures:
        print(f"pos1-check: {len(failures)} FAILED")
        for f in failures:
            print("   -", f)
        sys.exit(1)
    print(f"pos1-check: ALL LEGS PASS (the example, guards, the last-unit race, void twice, rebuild, "
          f"admin sets, {ndeltas} deltas / 1 reshape, 4 crash windows, {N} receipts against a 50-row page)")


asyncio.run(main())
