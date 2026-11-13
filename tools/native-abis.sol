ABI = use "native-abi".
> case args Unit of [root] -> print (Str.join " " (ABI.versions root))
  | _ -> error "usage: native-abis.sol FPRISC_ROOT".
