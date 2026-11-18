# Generate a board's device table from its manifest.
#
#   sol tools/board.sol bsp/BOARD/board.json OUTDIR      (from the QOS root)
#
# A board manifest lists device instances: a name, a driver, an optional base
# address, IRQ, driver parameters and a `when` macro that compiles the entry
# only in builds defining it. Each driver describes itself in
# hal/drivers/DRIVER.json: its device class, ops symbol, state type and setup,
# the parameters its state takes, and its sources. Plugging a driver into a
# board is one manifest line; the class primitives (hal/classes) do the rest.
#
# Writes OUTDIR/devtable.c (defines hal_devtable_ext, the machine layer's
# hook in FP-RISC machine/virt/devtable.h), OUTDIR/sources.txt (the class
# and driver C files to link, one absolute path a line) and OUTDIR/board.mk
# (the same list as QOS_BOARD_SOURCES, for hal/virt/qos-virt.mk).
unsafe program.
B = use "sol/lib/build".
J = use "sol/lib/json".
need r = case r of Ok x -> x | Err why -> error why.
openBrace = Str.fromCode 123.
textOr d key j = case J.get key j of Ok (J.JStr t) -> t | _ -> d.
listOf key j = case J.get key j of Ok (J.JArr xs) -> List.map (fn x -> need (J.text x)) xs | _ -> [].
# a class: (FPR_DEV_ id, header or "", ops type or "", class sources)
classInfo c = case c of
    "block" -> ("FPR_DEV_BLOCK","hal/classes/block.h","qos_block_ops",["hal/classes/block.c"])
  | "net" -> ("FPR_DEV_NET","","",[])
  | other -> error "unknown device class {other} (block, net)".
value v = case v of
    J.JNum n -> "{n}"
  | J.JStr s -> s
  | J.JBool b -> if b then "1" else "0"
  | other -> error "a parameter must be a number, string or boolean".
ident name = if List.all (fn c -> (c >= 48 and c <= 57) or (c >= 65 and c <= 90) or (c >= 97 and c <= 122) or c == 95) (Str.codes name) and name != ""
  then name else error "device name {name} must be letters, digits or _".
# a driver whose state owns a byte array sized by a parameter (memblk's pages)
storageOf name driverName params drv = case J.get "storage" drv of
    Err _ -> ([], [])
  | Ok spec ->
      field = need (J.text (need (J.get "field" spec)));
      count = need (J.text (need (J.get "count" spec)));
      unit = need (J.num (need (J.get "unit" spec)));
      n = case List.filter (fn kv -> (k,_) = kv; k == count) params of
          (_, v) :: _ -> value v
        | [] -> error "{name}: {driverName} needs parameter {count}";
      (["static uint8_t st_{name}_bytes[{n} * {unit}];"], [".{field} = st_{name}_bytes"]).
# one device: (C declarations, table entry, `when`, sources)
deviceEntry root d =
  name = ident (need (J.text (need (J.get "name" d))));
  driverName = need (J.text (need (J.get "driver" d)));
  drv = need (J.parse (readPath "{root}/hal/drivers/{driverName}.json"));
  cls = textOr "" "class" drv;
  (clsId, clsHeader, opsType, clsSources) = classInfo cls;
  ops = textOr "" "ops" drv;
  stateType = textOr "" "state" drv;
  header = textOr "" "header" drv;
  setup = textOr "" "setup" drv;
  stateSetup = textOr "" "state_setup" drv;
  allowed = listOf "params" drv;
  params = case J.get "params" d of Ok (J.JObj kvs) -> kvs | _ -> [];
  _ = List.map (fn kv -> (k,_) = kv; if List.has k allowed then Unit else error "{driverName} takes no parameter {k}") params;
  (storageDecl, storageInit) = storageOf name driverName params drv;
  inits = List.append (List.map (fn kv -> (k,v) = kv; ".{k} = {value v}") params) storageInit;
  initText = Str.join ", " inits;
  stateDecl = if stateType == "" then [] else List.append storageDecl ["static {stateType} st_{name} = {openBrace}{initText}};"];
  setupDecl = if stateSetup != "" then ["static void setup_{name}(void) {openBrace} {stateSetup}(&st_{name}); }"]
    else if setup != "" then ["extern void {setup}(void);"] else [];
  setupRef = if stateSetup != "" then "setup_{name}" else if setup != "" then setup else "NULL";
  opsDecl = if ops == "" then [] else ["extern const {opsType} {ops};"];
  base = case J.get "base" d of Ok v -> value v | Err _ -> "0";
  irq = case J.get "irq" d of Ok v -> value v | Err _ -> "0";
  fields = List.concat [[".cls = {clsId}"], (if irq != "0" then [".irq = {irq}"] else []),
    (if ops != "" then [".ops = &{ops}"] else []), (if stateType != "" then [".state = &st_{name}"] else [])];
  fieldText = Str.join ", " fields;
  entry = "  {openBrace}\"{name}\", {openBrace}T_DEVICE, 0, {base}}, {setupRef}, NULL, {fieldText}},";
  headers = List.filter (fn h -> h != "") [clsHeader, header];
  (List.concat [opsDecl, stateDecl, setupDecl], entry, textOr "" "when" d, List.append clsSources (listOf "sources" drv), headers).
guard when lines = if when == "" then lines else List.concat [["#ifdef {when}"], lines, ["#endif"]].
nub xs = List.fold (fn acc x -> if List.has x acc then acc else List.append acc [x]) [] xs.
> case args Unit of
    [manifest, out] ->
      root = B.query ["/bin/pwd","-P"];
      _ = (if B.exists "-f" "{root}/tools/board.sol" then Unit else error "run from the QOS root");
      board = need (J.parse (readPath manifest));
      boardName = textOr "?" "board" board;
      devs = case J.get "devices" board of Ok (J.JArr xs) -> List.map (deviceEntry root) xs | _ -> error "board.json has no devices";
      headers = nub (List.concat (List.map (fn d -> (_,_,_,_,h) = d; h) devs));
      decls = List.concat (List.map (fn d -> (c,_,w,_,_) = d; guard w c) devs);
      entries = List.concat (List.map (fn d -> (_,e,w,_,_) = d; guard w [e]) devs);
      sources = nub (List.concat (List.map (fn d -> (_,_,_,s,_) = d; s) devs));
      text = Str.join "\n" (List.concat [
        ["/* devtable.c -- board {boardName}: generated by tools/board.sol from {manifest}. Do not edit. */",
         "#include \"devtable.h\""],
        List.map (fn h -> "#include \"{root}/{h}\"") headers, [""], decls, ["",
        "static const devtable_entry_t board_devices[] = {openBrace}"], entries, ["};","",
        "const devtable_entry_t *hal_devtable_ext(uw *count) {openBrace}",
        "  *count = sizeof board_devices / sizeof board_devices[0];",
        "  return board_devices;","}",""]]);
      _ = B.command ["mkdir","-p",out];
      _ = writePath "{out}/devtable.c" text;
      _ = writePath "{out}/sources.txt" (Str.join "\n" (List.map (fn s -> "{root}/{s}") sources) + "\n");
      _ = writePath "{out}/board.mk" ("# generated by tools/board.sol from {manifest}\nQOS_BOARD_SOURCES := " + Str.join " " (List.map (fn s -> "{root}/{s}") sources) + "\n");
      print "board {boardName}: {List.len devs} devices -> {out}/devtable.c"
  | _ -> error "usage: sol tools/board.sol bsp/BOARD/board.json OUTDIR".
