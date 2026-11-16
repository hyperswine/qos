.option norvc
.globl _start
_start:
    lui sp,0x80380
    addi sp,sp,0
    la a0,console
    li a1,0
    li t0,0x800d1980
    jalr t0
    li t1,0x80500000
    sw a0,0(t1)
    j .
console:
    ret
