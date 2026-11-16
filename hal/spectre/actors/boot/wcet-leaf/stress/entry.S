.section .text.entry,"ax"
.global _start
_start:
    addi sp,sp,-64
    sw ra,28(sp)
    sw s0,24(sp)
    sw s1,20(sp)
    sw s2,16(sp)
    sw s3,12(sp)
    sw s4,8(sp)
    sw s5,4(sp)
    mv s0,a0
    li s1,0
.Lnext:
    la s2,fpr_fn_chooseRight
    # Vary the delay independently of the cache/write mode.
    srli t0,s1,2
    beqz t0,.Ldelaydone
.Ldelay:
    addi t0,t0,-1
    bnez t0,.Ldelay
.Ldelaydone:
    andi t0,s1,1
    beqz t0,.Lqueue
    # 2048 sets x 16 bytes: two other tags for each leaf line.
    li t3,0x8000
    xor t1,s2,t3
    slli t3,t3,1
    xor t2,s2,t3
    lw zero,0(t1)
    lw zero,0(t2)
    lw zero,16(t1)
    lw zero,16(t2)
    lw zero,32(t1)
    lw zero,32(t2)
    # Also evict the line used by chooseRight's two stack stores.
    addi t1,sp,-4
    xor t2,t1,t3
    srli t3,t3,1
    xor t1,t1,t3
    lw zero,0(t1)
    lw zero,0(t2)
.Lqueue:
    li a0,15
    slli a1,s1,1
    ori a1,a1,1
    csrrci s3,mstatus,8
    andi t0,s1,2
    beqz t0,.Lsample
    sw s1,32(sp)
    sw s1,36(sp)
    sw s1,40(sp)
    sw s1,-4(sp)
.Lsample:
    csrr s4,mcycle
    csrr s5,minstret
    jalr s2
    csrr t0,minstret
    csrr t1,mcycle
    andi s3,s3,8
    csrs mstatus,s3
    sw s4,48(sp)
    sub s4,t1,s4
    sub s5,t0,s5
    bne a0,a1,.Lfail
.Lprint:
    la a1,.Ldigits
    mv a0,s4
    jal ra,.Lhex
    addi a1,a1,1
    mv a0,s5
    jal ra,.Lhex
    addi a1,a1,1
    lw a0,48(sp)
    jal ra,.Lhex
    la a0,.Lstr
    jalr s0
    addi s1,s1,1
    li t0,2160
    blt s1,t0,.Lnext
    li a0,85
    j .Ldone
.Lfail:
    li a0,3
.Ldone:
    lw s5,4(sp)
    lw s4,8(sp)
    lw s3,12(sp)
    lw s2,16(sp)
    lw s1,20(sp)
    lw s0,24(sp)
    lw ra,28(sp)
    addi sp,sp,64
    ret
.Lempty:
    ret
.Lhex:
    li t2,8
.Ldigit:
    srli t0,a0,28
    li t1,10
    bltu t0,t1,.Ldecimal
    addi t0,t0,39
.Ldecimal:
    addi t0,t0,48
    sb t0,0(a1)
    addi a1,a1,1
    slli a0,a0,4
    addi t2,t2,-1
    bnez t2,.Ldigit
    ret
.balign 4
.Lstr:
    .word 9000,0,28
    .ascii "W "
.Ldigits:
    .ascii "00000000 00000000 00000000"
