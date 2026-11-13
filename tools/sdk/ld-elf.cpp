// ld.lld for the QOS Portable SDK: lld's ELF driver alone.
#include "lld/Common/Driver.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/raw_ostream.h"
LLD_HAS_DRIVER(elf)
int main(int argc, const char **argv) {
  llvm::InitLLVM x(argc, argv);
  std::vector<const char *> args(argv, argv + argc);
  lld::Result r = lld::lldMain(args, llvm::outs(), llvm::errs(), {{lld::Gnu, &lld::elf::link}});
  return r.retCode;
}
