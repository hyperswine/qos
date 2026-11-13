Seed = use "qlog-seed".
J = use "sol/lib/json".
buildArgs : unsafe Bool -> List (String,String) -> List String -> Unit .
buildArgs preserve extra argv = case argv of
    "--record" :: url :: file :: rest -> buildArgs preserve ((url,file) :: extra) rest
  | "--record" :: _ -> error "--record requires URL FILE"
  | image :: size :: apps -> Seed.freshDisk image (unwrap (J.num (unwrap (J.parse size)))) apps (List.rev extra) preserve
  | _ -> error "usage: mkdisk.sol [--record URL FILE ...] IMAGE SIZE_MIB [APP...]".
main : unsafe Unit -> Unit .
> case args Unit of "--preserve" :: rest -> buildArgs True [] rest | argv -> buildArgs False [] argv.
