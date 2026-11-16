# The UART actor probe on the board: sol run.sol uart.bin PORT
unsafe program.
R = use "../rom-lib".
> case args Unit of
    [image, port] ->
      out = R.uart port ["upload",image,"45","1","expect","READY A\n","5","delay","80","send-hex","41",
        "expect","READY B\n","5","delay","80","send-hex","5a","expect","DONE","5"];
      _ = print out;
      R.ensure "the scheduler ping/pong line is missing" (Str.contains "2 claims/acks; scheduler ping/pong OK" out)
  | _ -> error "usage: sol run.sol uart.bin PORT".
