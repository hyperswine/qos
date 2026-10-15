#!/usr/bin/env python3
"""Check the actual backported STAR64 loader functions, including wrap/error paths.

Run on Linux against a patched vendor kernel tree. Compiles extracted functions
with userspace shims and address/undefined sanitizers; does not load modules.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

PRELUDE = r'''
#include <assert.h>
#include <elf.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
typedef int32_t s32;
typedef Elf64_Rela Elf_Rela;
typedef Elf64_Sym Elf_Sym;
typedef Elf64_Shdr Elf_Shdr;
typedef Elf64_Addr Elf_Addr;
#define ELF_RISCV_R_TYPE ELF64_R_TYPE
#define ELF_RISCV_R_SYM ELF64_R_SYM
#define ELF_ST_BIND ELF64_ST_BIND
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define IS_ENABLED(x) 1
#define IS_ERR_VALUE(x) ((unsigned long)(x) >= (unsigned long)-4095)
#define pr_debug(...) ((void)0)
#define pr_err(...) ((void)0)
#define pr_warn(...) ((void)0)
#define GFP_KERNEL 0
struct module { const char *name; };
static int fail_alloc, live_alloc;
static void *kvmalloc_array(size_t n, size_t s, int flags) {
    (void)flags;
    if (fail_alloc) return NULL;
    void *p=calloc(n,s); if(p)live_alloc++; return p;
}
static void kvfree(void *p) { if(p)live_alloc--; free(p); }
#define sort(p,n,s,cmp,swap) qsort(p,n,s,cmp)
static unsigned long got;
static unsigned long module_emit_got_entry(struct module *m, unsigned long v) {
    (void)m; (void)v; return got;
}
static int record(struct module *m, u32 *location, Elf_Addr v) {
    (void)m; *location=(u32)v; return 0;
}
static int (*reloc_handlers_rela[64])(struct module *, u32 *, Elf_Addr);
'''
TESTS = r'''
static uint32_t rng=42;
static unsigned random_u(void) { rng=rng*1664525+1013904223; return rng; }
static void count_reference(Elf_Rela *r, size_t n, unsigned *p, unsigned *g) {
    for(size_t i=0;i<n;i++) {
        unsigned t=ELF64_R_TYPE(r[i].r_info);
        if(t!=R_RISCV_CALL_PLT && t!=R_RISCV_GOT_HI20)continue;
        size_t j;
        for(j=0;j<i;j++)if(r[j].r_info==r[i].r_info&&r[j].r_addend==r[i].r_addend)break;
        if(j==i) { if(t==R_RISCV_CALL_PLT)(*p)++; else (*g)++; }
    }
}
static void check_counts(void) {
    Elf_Rela r[256], saved[256];
    for(unsigned pass=0;pass<300;pass++) {
        size_t n=pass%257;
        for(size_t i=0;i<n;i++) {
            unsigned t[]={R_RISCV_CALL_PLT,R_RISCV_GOT_HI20,R_RISCV_64,R_RISCV_PCREL_HI20};
            r[i]=(Elf_Rela){.r_offset=i*4,.r_info=ELF64_R_INFO(random_u()%13,t[random_u()%4]),
                .r_addend=(int)(random_u()%7)-3};
            if(i%17==0)r[i].r_addend=INT64_MIN;
            if(i%19==0)r[i].r_addend=INT64_MAX;
        }
        memcpy(saved,r,n*sizeof(*r));
        unsigned p=7,g=9,ep=7,eg=9; count_reference(r,n,&ep,&eg);
        assert(count_max_entries(r,n,&p,&g)==0);
        assert(p==ep&&g==eg&&!live_alloc&&!memcmp(saved,r,n*sizeof(*r)));
    }
    unsigned p=4,g=5; fail_alloc=1;
    assert(count_max_entries(r,1,&p,&g)==-ENOMEM);
    assert(p==4&&g==5&&!live_alloc);
    assert(count_max_entries(r,0,&p,&g)==0); fail_alloc=0;
    puts("PLT/GOT: reference counts, original order, extreme addends, empty section and allocation failure PASS");
}
static void apply(Elf_Rela *r,size_t n,Elf_Sym *sym,u32 *text,int expected) {
    Elf_Shdr sh[4]={0}; struct module m={.name="test"};
    sh[1].sh_addr=(uintptr_t)sym;
    sh[2].sh_addr=(uintptr_t)r; sh[2].sh_size=n*sizeof(*r); sh[2].sh_info=3;
    sh[3].sh_addr=(uintptr_t)text;
    assert(apply_relocate_add(sh,"",1,2,&m)==expected);
}
static void check_pairing(void) {
    u32 text[512]; Elf_Sym sym[64]={0}; Elf_Rela r[64];
    for(unsigned i=0;i<ARRAY_SIZE(reloc_handlers_rela);i++)reloc_handlers_rela[i]=record;
    for(unsigned pass=0;pass<300;pass++) {
        memset(text,0,sizeof(text));
        sym[0].st_value=(uintptr_t)text+0x1234;
        for(unsigned i=0;i<24;i++) {
            unsigned hi=i*8,lo=hi+4;
            sym[i+1].st_value=(uintptr_t)text+hi;
            r[2*i]=(Elf_Rela){.r_offset=hi,.r_info=ELF64_R_INFO(0,R_RISCV_PCREL_HI20)};
            r[2*i+1]=(Elf_Rela){.r_offset=lo,.r_info=ELF64_R_INFO(i+1,i%2?R_RISCV_PCREL_LO12_I:R_RISCV_PCREL_LO12_S)};
        }
        /* Exercise arbitrary ordering and targets before the cached position. */
        for(unsigned i=47;i>0;i--) {
            unsigned j=random_u()%(i+1); Elf_Rela tmp=r[i]; r[i]=r[j]; r[j]=tmp;
        }
        apply(r,48,sym,text,0);
        for(unsigned i=0;i<24;i++) {
            int64_t offset=0x1234-i*8;
            assert(text[(i*8+4)/4]==(u32)(offset-((offset+0x800)&~INT64_C(0xfff))));
        }
    }
    /* The match is the final relocation. Next lookup wraps and has no match. */
    memset(text,0,sizeof(text));
    sym[1].st_value=(uintptr_t)text+8; sym[2].st_value=(uintptr_t)text+1000;
    r[0]=(Elf_Rela){.r_offset=0,.r_info=ELF64_R_INFO(1,R_RISCV_PCREL_LO12_I)};
    r[1]=(Elf_Rela){.r_offset=4,.r_info=ELF64_R_INFO(2,R_RISCV_PCREL_LO12_S)};
    r[2]=(Elf_Rela){.r_offset=8,.r_info=ELF64_R_INFO(0,R_RISCV_PCREL_HI20)};
    apply(r,3,sym,text,-EINVAL);
    sym[1].st_value=(uintptr_t)text+1000;
    apply(r,1,sym,text,-EINVAL); apply(r,0,sym,text,0);
    /* GOT pairing uses the GOT address, not the symbol's direct address. */
    got=(uintptr_t)text+0x2345; sym[1].st_value=(uintptr_t)text+8;
    r[0]=(Elf_Rela){.r_offset=0,.r_info=ELF64_R_INFO(1,R_RISCV_PCREL_LO12_I)};
    r[1]=(Elf_Rela){.r_offset=8,.r_info=ELF64_R_INFO(0,R_RISCV_GOT_HI20)};
    apply(r,2,sym,text,0); assert(text[0]==0x33d);
    puts("HI20: I/S pairing, shuffled order, backward wrap, final entry, missing match, empty section and GOT PASS");
}
int main(void) { check_counts(); check_pairing(); }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--cc', default='cc')
    args = parser.parse_args()
    directory = args.kernel / 'arch/riscv/kernel'
    module = (directory / 'module.c').read_text()
    sections = (directory / 'module-sections.c').read_text()
    apply_function = module[module.index('int apply_relocate_add('):module.index('\n#if defined(CONFIG_MMU)', module.index('int apply_relocate_add('))]
    count_functions = sections[sections.index('static int cmp_rela('):sections.index('\nint module_frob_arch_sections(')]
    with tempfile.TemporaryDirectory(prefix='star64-loader-check-') as scratch:
        source = Path(scratch) / 'check.c'
        binary = Path(scratch) / 'check'
        source.write_text(PRELUDE + count_functions + apply_function + TESTS)
        subprocess.run([args.cc, '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == '__main__':
    main()
