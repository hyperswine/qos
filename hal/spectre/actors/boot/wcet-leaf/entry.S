.section .text.entry,"ax"
.global _start
_start:
    addi sp,sp,-32
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
    la s2,.Lempty
    andi t0,s1,1
    beqz t0,.Lsample
    la s2,fpr_fn_chooseRight
.Lsample:
    li a0,15
    slli a1,s1,1
    ori a1,a1,1
    csrrci s3,mstatus,8
    csrr s4,mcycle
    csrr s5,minstret
    jalr s2
    csrr t0,minstret
    csrr t1,mcycle
    andi s3,s3,8
    csrs mstatus,s3
    sub s4,t1,s4
    sub s5,t0,s5
    andi t0,s1,1
    beqz t0,.Lprint
    bne a0,a1,.Lfail
.Lprint:
    la a1,.Ldigits
    mv a0,s4
    jal ra,.Lhex
    addi a1,a1,1
    mv a0,s5
    jal ra,.Lhex
    la a0,.Lstr
    jalr s0
    addi s1,s1,1
    li t0,32
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
    addi sp,sp,32
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
    .word 9000,0,19
    .ascii "W "
.Ldigits:
    .ascii "00000000 00000000"
