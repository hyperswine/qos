.section .text.entry,"ax"
.globl _start
_start:
    la t0,.Lconsole
    sw a0,0(t0)
    sw a1,4(t0)
#ifdef SPECTRE_MAILBOX
    sw a2,8(t0)
    sw a3,12(t0)
#endif
    tail fpr_fn_main
.globl fpr_g_spectrePut_call1
fpr_g_spectrePut_call1:
    la t0,.Lconsole
    lw t0,0(t0)
    jr t0
.balign 4
.Lconsole:
    .word 0
    .word 0
#ifdef SPECTRE_MAILBOX
    .word 0
    .word 0
.globl fpr_g_peerSend_call1
fpr_g_peerSend_call1:
    la t0,.Lconsole
    lw t0,8(t0)
    jr t0
.globl fpr_g_mailReceive_call1
fpr_g_mailReceive_call1:
    la t0,.Lconsole
    lw t0,12(t0)
    jr t0
#endif
.globl spectre_poll
spectre_poll:
    addi sp,sp,-64
    sw ra,0(sp)
    sw t0,4(sp)
    sw t1,8(sp)
    sw t2,12(sp)
    sw t3,16(sp)
    sw t4,20(sp)
    sw t5,24(sp)
    sw t6,28(sp)
    sw a0,32(sp)
    sw a1,36(sp)
    sw a2,40(sp)
    sw a3,44(sp)
    sw a4,48(sp)
    sw a5,52(sp)
    sw a6,56(sp)
    sw a7,60(sp)
    la t0,.Lconsole
    lw t0,4(t0)
    jalr t0
    lw ra,0(sp)
    lw t0,4(sp)
    lw t1,8(sp)
    lw t2,12(sp)
    lw t3,16(sp)
    lw t4,20(sp)
    lw t5,24(sp)
    lw t6,28(sp)
    lw a0,32(sp)
    lw a1,36(sp)
    lw a2,40(sp)
    lw a3,44(sp)
    lw a4,48(sp)
    lw a5,52(sp)
    lw a6,56(sp)
    lw a7,60(sp)
    addi sp,sp,64
    ret
