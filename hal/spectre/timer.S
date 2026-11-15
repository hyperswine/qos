// Spectre RV32IM foreground/trap smoke test. No QOS scheduler yet.
.section .text
.global fpr_builtin_main
fpr_builtin_main:
    csrci mstatus,8
    la t0,trap
    csrw mtvec,t0
    jal ra,arm
    li t0,128
    csrw mie,t0
    csrsi mstatus,8
    la t0,ticks
1:  lw t1,0(t0)
    li t2,2
    bltu t1,t2,1b
    la a0,ok
    j print
.balign 4
trap:
    addi sp,sp,-16
    sw t0,0(sp)
    sw t1,4(sp)
    sw ra,8(sp)
    csrr t0,mcause
    li t1,0x80000007
    bne t0,t1,fail
    la t0,ticks
    lw t1,0(t0)
    addi t1,t1,1
    sw t1,0(t0)
    jal ra,arm
    lw t0,0(sp)
    lw t1,4(sp)
    lw ra,8(sp)
    addi sp,sp,16
    mret
arm:
    // Read a consistent RV32 timestamp; schedule 1M core clocks ahead.
    addi sp,sp,-16
    sw t2,0(sp)
    sw t3,4(sp)
    li t0,0x0200bff8
2:  lw t1,4(t0)
    lw t2,0(t0)
    lw t3,4(t0)
    bne t1,t3,2b
    li t3,1000000
    add t3,t2,t3
    sltu t2,t3,t2
    add t1,t1,t2
    li t0,0x02004000
    li t2,-1
    sw t2,0(t0)
    sw t1,4(t0)
    sw t3,0(t0)
    lw t2,0(sp)
    lw t3,4(sp)
    addi sp,sp,16
    ret
fail:
    la a0,bad
print:
    csrci mstatus,8
    li t0,0x10000000
3:  lbu t1,0(a0)
    beqz t1,5f
4:  lw t2,4(t0)
    andi t2,t2,1
    beqz t2,4b
    sw t1,0(t0)
    addi a0,a0,1
    j 3b
5:  j 5b
.section .rodata
ok: .asciz "spectre timer-v1: two timer returns OK\r\n"
bad: .asciz "spectre timer-v1: unexpected trap\r\n"
.section .bss
.balign 4
ticks: .space 4
