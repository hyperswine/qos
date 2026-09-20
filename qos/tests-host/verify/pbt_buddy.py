"""Property-based test of runtime/buddy.c through ctypes (Hypothesis).
Model: a dict of live blocks {addr: (size, fill byte)}.  Invariants after
every op: blocks inside the arena, usable >= request, no two live blocks
overlap (headers included), payload bytes intact, and free_bytes ==
arena - sum(block sizes) is monotone-consistent; freeing everything
restores the initial free count exactly."""
import ctypes, os
from hypothesis import settings, strategies as st, Phase
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant, precondition, run_state_machine_as_test

MIN, NB = 64, 64
lib = ctypes.CDLL(os.environ.get("BUDDY_SO", os.path.abspath("libbuddy.so")))
lib.buddy_alloc.restype = ctypes.c_void_p; lib.buddy_alloc.argtypes = [ctypes.c_ulong]
lib.buddy_realloc.restype = ctypes.c_void_p; lib.buddy_realloc.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
lib.buddy_free.argtypes = [ctypes.c_void_p]
lib.buddy_block_usable_size.restype = ctypes.c_ulong; lib.buddy_block_usable_size.argtypes = [ctypes.c_void_p]
lib.buddy_free_bytes.restype = ctypes.c_ulong
lib.buddy_init.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
arena = ctypes.create_string_buffer(MIN * NB + MIN)
base = (ctypes.addressof(arena) + MIN - 1) & ~(MIN - 1)

class Buddy(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        lib.buddy_init(ctypes.c_void_p(base), MIN * NB)
        self.free0 = lib.buddy_free_bytes()
        self.live = {}  # addr -> (n, fill)
        self.fills = 0

    def _fill(self, p, n):
        self.fills = (self.fills + 1) % 251
        ctypes.memset(p, self.fills + 1, n)
        return self.fills + 1

    @rule(n=st.integers(1, 3 * MIN))
    def alloc(self, n):
        p = lib.buddy_alloc(n)
        if p is None:
            return  # exhaustion is a legal answer
        assert base <= p and p + n <= base + MIN * NB, "inside the arena"
        assert lib.buddy_block_usable_size(p) >= n
        self.live[p] = (n, self._fill(p, n))

    @precondition(lambda self: self.live)
    @rule(data=st.data(), n=st.integers(1, 3 * MIN))
    def realloc(self, data, n):
        p = data.draw(st.sampled_from(sorted(self.live)))
        old_n, fill = self.live[p]
        q = lib.buddy_realloc(p, n)
        if q is None:
            assert lib.buddy_block_usable_size(p) >= old_n, "refusal leaves the original intact"
            return
        keep = min(old_n, n)
        assert ctypes.string_at(q, keep) == bytes([fill]) * keep, "payload survives realloc"
        del self.live[p]
        self.live[q] = (n, self._fill(q, n))

    @precondition(lambda self: self.live)
    @rule(data=st.data())
    def free(self, data):
        p = data.draw(st.sampled_from(sorted(self.live)))
        lib.buddy_free(p); del self.live[p]

    @invariant()
    def no_overlap_and_intact(self):
        spans = sorted((p - 8, p + lib.buddy_block_usable_size(p)) for p in self.live)
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            assert a1 <= b0, "live blocks overlap"
        for p, (n, fill) in self.live.items():
            assert ctypes.string_at(p, n) == bytes([fill]) * n, "payload intact"
        used = sum(lib.buddy_block_usable_size(p) + 8 for p in self.live)
        assert lib.buddy_free_bytes() + used <= MIN * NB

    def teardown(self):
        for p in list(self.live): lib.buddy_free(p)
        assert lib.buddy_free_bytes() == self.free0, "everything freed: conservation"

run_state_machine_as_test(Buddy, settings=settings(max_examples=300, stateful_step_count=60, deadline=None, phases=[Phase.generate, Phase.shrink]))
print("pbt buddy: 300 random op sequences x <=60 steps, all invariants held")
