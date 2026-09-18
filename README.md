# QOS

QOS Native, QOS Portable, their HAL and services, and the `qos.py` application driver.
The compiler and language runtime are developed in the separate `fprisc` repository.

Set the compiler checkout explicitly (it can be anywhere):

```sh
export FPRISC_ROOT=/Users/jasonqin/Documents/GitHub/fprisc
./qos.py build
./qos.py run tests/hello.fpr
./qos.py run programs/interactive_desktop_gl.fpr
```

The same variable is used by the Makefiles and host checks. No setup step, source
copies, compiler wrappers or dependency symlinks are generated. `./configure.py
--check` optionally validates the path; `./configure.py --pin` records a clean
compiler commit for releases. Put the export in your shell configuration if desired.

- `qos/`: portable host, native entry, application-side HAL and host checks.
- `hal/unix/`: Unix devices and graphics/audio/input backends.
- `hal/core/`: QOS application/process/image loaders.
- `fp-risc/programs/`: QOS kernel, services and examples.
- `fp-risc/{apps,models,std,tests,tools}/`: QOS application resources,
  service clients, integration checks and packaging tools owned by QOS.
- `qos.py`: build, run, disk, bundle, install and release commands.

`fp-risc/` contains QOS programs written in FP-RISC and their application build
rules. The compiler, runtime and language libraries remain exclusively in
`FPRISC_ROOT`. `FPR_PATH` supplies module search roots; `qos.py` and the Makefiles
set it together with the QOS module home. The root `fprisc.lock.json` pins the
compiler Git revision; `fp-risc/fpr.lock` independently pins QOS modules.

See [the split guide](docs/REPOSITORY-SPLIT.md) for the full ownership map,
validation, and the release transition. The previous combined README and tag
workflow are preserved under `docs/history/` as historical reference.
