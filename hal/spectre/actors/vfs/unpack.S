.section .text
.option norelax
.global _start
_start:
    la t0,body
    la t1,end
    li t2,0x80600000
    mv t3,t2
1:  lbu t4,0(t0)
    sb t4,0(t3)
    addi t3,t3,1
    addi t0,t0,1
    bne t0,t1,1b
    fence.i
    jr t2
.balign 4
body:
    la a0,data
    la a1,end
    li a2,0x80000000
loop:
    lbu a3,0(a0)
    addi a0,a0,1
    srli a4,a3,4
    jal t0,extend
    beqz a4,offset
2:  lbu t1,0(a0)
    sb t1,0(a2)
    addi a0,a0,1
    addi a2,a2,1
    addi a4,a4,-1
    bnez a4,2b
offset:
    beq a0,a1,finish
    lbu t1,0(a0)
    lbu t2,1(a0)
    slli t2,t2,8
    or t1,t1,t2
    sub a5,a2,t1
    addi a0,a0,2
    andi a4,a3,15
    jal t0,extend
    addi a4,a4,4
3:  lbu t1,0(a5)
    sb t1,0(a2)
    addi a5,a5,1
    addi a2,a2,1
    addi a4,a4,-1
    bnez a4,3b
    j loop
extend:
    li t2,15
    bne a4,t2,4f
    li t2,255
5:  lbu t1,0(a0)
    addi a0,a0,1
    add a4,a4,t1
    beq t1,t2,5b
4:  jr t0
finish:
    fence.i
    li t0,0x80000000
    jr t0
data:
.incbin "packed.lz4"
end:
