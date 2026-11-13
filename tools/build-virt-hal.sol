HAL = use "virt-hal".
> case args Unit of [compiler,hal,build,unit] -> HAL.compile [] compiler hal build unit
  | _ -> error "usage: build-virt-hal COMPILER HAL BUILD UNIT".
