#!/bin/bash
set -eu
: "${SIMPLE_RISC:?set to the Simple-Risc checkout}"
tar -xzf "$SIMPLE_RISC/docs/evidence/2026-10-30-structural/baseline-sources.tar.gz" sdram/pipeline_cache.v sdram/burst_memory.v sdram/sdram.v
gzip -dc "$SIMPLE_RISC/docs/evidence/2026-10-30-structural/builds/existing-54/bootrom-sdram.hex.gz" > rom.hex
iverilog -g2012 -s tb -o sim controller_tb.v sdram/*.v
vvp sim
