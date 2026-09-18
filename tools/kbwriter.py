import struct, time, os, sys
# struct input_event (x86-64): timeval(16) + type u16 + code u16 + value u32
def ev(code, value=1):
    return struct.pack('<qqHHI', 0, 0, 1, code, value)  # EV_KEY

UP, DOWN, LEFT, RIGHT = 103, 108, 105, 106
W, S, A, D, X, F, SPACE, Q = 17, 31, 30, 32, 45, 33, 57, 16
K9 = 10          # '9' -> code 10 -> block 9 brick
script = [
    (1.0, [UP, UP, UP]),           # walk forward 3 frames' worth
    (0.5, [D, D]),                 # yaw right twice
    (0.5, [UP, UP]),               # forward again
    (0.8, [S, S]),                 # pitch down toward the ground
    (0.5, [X]),                    # destroy -> incremental rebake
    (0.5, [K9]),                   # select brick
    (0.4, [F]),                    # place -> rebake again
    (0.5, [SPACE]),                # jump
    (0.5, [A, UP]),                # yaw left, forward
    (8.0, []),                     # idle soak: ~160 frames of steady state
    (0.0, [Q]),
]
fifo = sys.argv[1]
fd = os.open(fifo, os.O_WRONLY)    # blocks until qosp opens the read side
for delay, keys in script:
    time.sleep(delay)
    for k in keys:
        os.write(fd, ev(k, 1))
        os.write(fd, ev(k, 0))     # release: decode discipline sees both
os.close(fd)
