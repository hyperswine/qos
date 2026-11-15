{-# LANGUAGE ScopedTypeVariables #-}
-- qos-fprd: the QOS compiler daemon, native.
--
-- It replaces tools/fprd.py and the Pi SDK's Python runner (both retired in
-- the Sol-only cutover). The protocol is the one qos/portable/compile.c
-- speaks, unchanged:
--
--   socket   --socket PATH, else $FPRD_SOCK, else /tmp/fprd.sock; made 0600.
--            A path that is not a socket, or is another user's, is refused
--            rather than replaced (qosp checks the server's uid too).
--   frame    4-byte little-endian length + payload, both directions.
--   request  "<profile>\n<source bytes>"; the profile is a whitelisted token,
--            never passed through to a command line:
--              qos-portable | bare-metal    whole-program assembly
--              check                        the front end only (types, safety,
--                                           linearity, contracts), nothing linked
--              plugin:<slot>:<id>           a relocatable plugin .qa (the slot is
--                                           the old protocol's and is ignored)
--              publication:<id>             commit a checked version, then its
--                                           frozen .qa
--              watch:<id>:<hash or ->       a publication of a file registered
--                                           with --watch ID=FILE
--   reply    "ok\n<bytes>" | "err\n<message>". A publication's bytes are
--            "name<TAB>version<TAB>root-hash<LF>" then the .qa; an unchanged
--            watch answers "ok\nsame\n".
--
-- One connection at a time, requests served in order, each compile a child
-- process with its own deadline (the compiler and `make plugin-qa`), so a
-- compiler crash or runaway build never takes the daemon with it. The daemon
-- writes no QOS storage and attaches nothing: QOS keeps that policy.
--
-- Two layouts:
--   SDK      the executable is <root>/bin/qos-fprd beside <root>/sdk.json (the
--            Pi's compiler SDK). Compiler, sources, make, gcc and sol all come
--            from <root>; --work holds builds, caches and temporaries.
--   checkout FPRISC_ROOT names the fprisc checkout and FPR_HOME the qos one
--            (what tools/fprd.py required). SOL selects the Sol runner.
--
-- Commands:
--   qos-fprd daemon [--socket PATH] [--work DIR] [--watch ID=FILE]...
--   qos-fprd selftest
--   qos-fprd request [--socket PATH] PROFILE [FILE]
-- `request` sends one request (FILE's bytes, or none) to a running daemon and
-- writes the reply after its status line to stdout (exit 0 on "ok", 1 on
-- "err"): the probe an install uses against the installed service.
-- `daemon` writes its pid to $QOSP_READY_FILE once it is listening, exits 0
-- on SIGTERM or SIGINT (the supervisor's acknowledged stop) and nonzero on any
-- other ending. `selftest` starts a real daemon on a private socket and drives
-- check, plugin, publication (stable and updated) and a refused source
-- through the wire protocol; it does not load the plugin into qosp.
module Main (main) where

import Control.Concurrent (forkIO, myThreadId, newEmptyMVar, putMVar, takeMVar, threadDelay)
import Control.Exception
import Control.Monad (forM, forM_, unless, when)
import Data.Bits (shiftL, shiftR, (.&.), (.|.))
import qualified Data.ByteString as B
import qualified Data.ByteString.Char8 as BC
import Data.Char (isDigit, isHexDigit, isLower)
import Data.IORef
import Data.List (isPrefixOf, isSuffixOf, sort)
import qualified Data.Map.Strict as M
import Data.Maybe (fromMaybe, listToMaybe)
import Data.Word (Word32)
import Network.Socket
import qualified Network.Socket.ByteString as NB
import System.Directory
import System.Environment (getArgs, getEnvironment, getExecutablePath, lookupEnv)
import System.Exit
import System.FilePath
import System.IO
import System.IO.Error (isDoesNotExistError)
import qualified System.Info as Info
import System.Posix.Files
import System.Posix.IO (closeFd, defaultFileFlags, openFd, OpenMode (WriteOnly), creat, setLock, LockRequest (WriteLock))
import System.Posix.Process (getProcessID)
import System.Posix.Signals
import System.Posix.Types (CPid)
import System.Posix.User (getRealUserID)
import System.Process
import System.IO.Unsafe (unsafePerformIO)
import System.Timeout (timeout)

-- ---- configuration -------------------------------------------------------

data Cfg = Cfg
  { cfRoot :: FilePath, -- the fprisc tree (FPRISC_ROOT)
    cfHome :: FilePath, -- the qos tree (FPR_HOME)
    cfCompiler :: FilePath,
    cfBuild :: FilePath, -- FPRD_BUILD: package intermediates, versions, temporaries
    cfEnv :: [(String, String)], -- every child's environment
    cfTarget :: String, -- the plugin target this host's qosp runs
    cfWatches :: M.Map String FilePath,
    cfChild :: IORef (Maybe CPid) -- the running build, killed with the daemon
  }

maxRequest :: Int
maxRequest = 4 * 1024 * 1024 -- a 4 MiB source bound: an honest refusal, not an OOM

connectionTimeout :: Int
connectionTimeout = 30 -- seconds a client may take to send its frame

pluginTarget :: String
pluginTarget = case Info.arch of
  "aarch64" -> "qa64"
  "arm64" -> "qa64"
  "riscv64" -> "qrv64"
  _ -> "qx64"

-- the SDK root when this executable is <root>/bin/qos-fprd beside sdk.json
sdkRoot :: IO (Maybe FilePath)
sdkRoot = do
  exe <- getExecutablePath >>= canonicalizePath
  let root = takeDirectory (takeDirectory exe)
  ok <- doesFileExist (root </> "sdk.json")
  pure (if ok then Just root else Nothing)

configure :: FilePath -> [(String, FilePath)] -> IO Cfg
configure work watches = do
  createDirectoryIfMissing True work
  workAbs <- canonicalizePath work
  base <- getEnvironment
  sdk <- sdkRoot
  (root, home, sets) <- case sdk of
    Just r -> do
      let tmp = workAbs </> "tmp"
      createDirectoryIfMissing True tmp
      pure
        ( r </> "fprisc",
          r </> "qos",
          [ ("FPRISC_ROOT", r </> "fprisc"),
            ("FPR_HOME", r </> "qos"),
            ("FPR_PATH", r </> "fprisc"),
            ("FPR_FOREIGN", r </> "qos/core/foreign.fpr"),
            ("FPRD_BUILD", workAbs </> "build"),
            ("TMPDIR", tmp),
            ("SOL", r </> "bin/sol"),
            ("XDG_STATE_HOME", workAbs </> "state"),
            ("XDG_CACHE_HOME", workAbs </> "cache"),
            -- the compiler is built with -rtsopts: bound its live heap and stack
            ("GHCRTS", "-M512m -K64m"),
            ("PATH", r </> "bin" ++ ":/usr/bin:/bin"),
            -- gcc only assembles native .s and invokes collect2/ld: no cc1,
            -- headers, C runtime or system library is reached
            ("COMPILER_PATH", r </> "bin"),
            ("LD_LIBRARY_PATH", r </> "lib"),
            ( "PLUG_A64_LINK",
              "gcc -fno-use-linker-plugin -nostdlib -nostartfiles -static -no-pie "
                ++ "-Wl,--build-id=none -Wl,-z,noexecstack -Wl,--no-relax "
                ++ "-T $(QOS)/appside/link-qosplug.ld -Wl,--emit-relocs"
            )
          ]
        )
    Nothing -> do
      root <- maybe (die "qos-fprd: set FPRISC_ROOT to the fprisc checkout (or run the SDK's bin/qos-fprd)") pure =<< lookupEnv "FPRISC_ROOT"
      home <- maybe (die "qos-fprd: set FPR_HOME to the qos checkout") pure =<< lookupEnv "FPR_HOME"
      build <- fromMaybe (workAbs </> "build") <$> lookupEnv "FPRD_BUILD"
      pure
        ( root,
          home,
          [ ("FPRISC_ROOT", root),
            ("FPR_HOME", home),
            ("FPR_PATH", root),
            ("FPR_FOREIGN", home </> "core/foreign.fpr"),
            ("FPRD_BUILD", build)
          ]
        )
  let env = M.toList (M.insert "LC_ALL" "C.UTF-8" (M.union (M.fromList sets) (M.fromList base)))
      build = fromMaybe (workAbs </> "build") (lookup "FPRD_BUILD" env)
  createDirectoryIfMissing True build
  buildAbs <- canonicalizePath build
  watchMap <- M.fromList <$> mapM (\(n, f) -> (,) n <$> canonicalizePath f) watches
  child <- newIORef Nothing
  let compiler = root </> "fpr"
  ok <- doesFileExist compiler
  unless ok (die ("qos-fprd: no compiler at " ++ compiler))
  pure (Cfg root home compiler buildAbs env pluginTarget watchMap child)

-- ---- child processes -----------------------------------------------------

data Ran = Ran ExitCode B.ByteString -- the exit, then stderr followed by stdout

-- Run a child in its own process group with a deadline. On expiry the whole
-- group is killed and the answer is Nothing.
run :: Cfg -> FilePath -> Int -> [String] -> IO (Maybe Ran)
run cfg dir seconds argv = do
  let (cmd, cmdArgs) = case argv of
        c : rest -> (c, rest)
        [] -> error "run: empty command"
      cp =
        (proc cmd cmdArgs)
          { cwd = Just dir,
            env = Just (cfEnv cfg),
            std_in = NoStream,
            std_out = CreatePipe,
            std_err = CreatePipe,
            create_group = True
          }
  bracket (createProcess cp) cleanup $ \(_, Just hout, Just herr, ph) -> do
    pid <- getPid ph
    writeIORef (cfChild cfg) pid
    outV <- newEmptyMVar
    errV <- newEmptyMVar
    _ <- forkIO (B.hGetContents hout >>= putMVar outV)
    _ <- forkIO (B.hGetContents herr >>= putMVar errV)
    done <- timeout (seconds * 1000000) (waitForProcess ph)
    case done of
      Nothing -> do
        killGroup pid
        _ <- waitForProcess ph
        writeIORef (cfChild cfg) Nothing
        pure Nothing
      Just code -> do
        o <- takeMVar outV
        e <- takeMVar errV
        writeIORef (cfChild cfg) Nothing
        pure (Just (Ran code (B.append e o)))
  where
    cleanup (_, o, e, ph) = do
      st <- getProcessExitCode ph
      when (st == Nothing) (getPid ph >>= killGroup >> () <$ waitForProcess ph)
      mapM_ hClose o
      mapM_ hClose e

killGroup :: Maybe CPid -> IO ()
killGroup Nothing = pure ()
killGroup (Just pid) = signalProcessGroup sigKILL pid `catch` \(_ :: IOException) -> pure ()

-- what a failed build said, without the build's progress chatter
noise :: [B.ByteString]
noise =
  map BC.pack
    [ "use: ", "unit ", "autodrop: ", "precond: ", "linear types: ", "wrote ",
      "module table: ", "assumed external", "mkimports: ", "make: ", "make[",
      "typed-ir-backend: ", "string pieces: ", "# ", "fpr build: "
    ]

diagnostics :: B.ByteString -> String -> B.ByteString
diagnostics text fallback =
  let keep l = not (B.null (BC.strip l)) && not (any (`B.isPrefixOf` l) noise)
      ls = filter keep (BC.lines (BC.strip text))
   in if null ls then BC.pack fallback else BC.intercalate (BC.pack "\n") ls

err :: String -> B.ByteString
err s = BC.pack ("err\n" ++ s)

errB :: B.ByteString -> B.ByteString
errB b = B.append (BC.pack "err\n") b

okB :: B.ByteString -> B.ByteString
okB b = B.append (BC.pack "ok\n") b

-- a fresh private directory under the build directory
withScratch :: Cfg -> (FilePath -> IO a) -> IO a
withScratch cfg act = do
  pid <- getProcessID
  n <- atomicModifyIORef' scratchCounter (\k -> (k + 1, k))
  let dir = cfBuild cfg </> "tmp" </> ("fprd-" ++ show pid ++ "-" ++ show n)
  createDirectoryIfMissing True dir
  act dir `finally` (removePathForcibly dir `catch` \(_ :: IOException) -> pure ())

{-# NOINLINE scratchCounter #-}
scratchCounter :: IORef Int
scratchCounter = unsafePerformIO (newIORef 0)

-- ---- operations ------------------------------------------------------------

prelude :: Cfg -> String
prelude cfg = "--prelude=" ++ (cfRoot cfg </> "core/prelude.fpr")

-- check: the front end as a plugin build runs it, nothing generated or linked
checkSource :: Cfg -> B.ByteString -> IO B.ByteString
checkSource cfg source = withScratch cfg $ \td -> do
  let src = td </> "qedcheck.fpr"
  B.writeFile src source
  r <- run cfg td 120 [cfCompiler cfg, "--target=" ++ cfTarget cfg, "--plugin", "--check-only", prelude cfg, src, td </> "out.s"]
  pure $ case r of
    Nothing -> err "compile timed out"
    Just (Ran ExitSuccess _) -> BC.pack "ok\n"
    Just (Ran _ out) -> errB (diagnostics out "check failed")

-- whole-program assembly for the two named profiles
compileProfile :: Cfg -> String -> B.ByteString -> IO B.ByteString
compileProfile cfg profile source = withScratch cfg $ \td -> do
  let src = td </> "in.fpr"
      out = td </> "out.s"
  B.writeFile src source
  r <- run cfg td 120 [cfCompiler cfg, "--profile=" ++ profile, prelude cfg, src, out]
  exists <- doesFileExist out
  case r of
    Nothing -> pure (err "compile timed out")
    Just (Ran ExitSuccess _) | exists -> okB <$> B.readFile out
    Just (Ran _ o) -> pure (errB (let s = BC.strip o in if B.null s then BC.pack "compile failed" else s))

-- What a plugin can reach: the compiler, the ABI stamp, link scripts and
-- packaging tools, the trust list and every module under the import roots,
-- by path, mtime and size. An edit to any of them misses the package cache.
reachable :: Cfg -> IO B.ByteString
reachable cfg = do
  let home = cfHome cfg
      root = cfRoot cfg
      fixed =
        [cfCompiler cfg]
          ++ map (home </>)
            [ "qos/appside/qos_abi.h", "qos-app.mk", "tools/app-manifest.sol", "tools/qa-pack.sol",
              "tools/elf-image.sol", "tools/qa-relocations.sol", "tools/qa-moved.sol", "tools/qa-imports.sol",
              "tools/mkimports.sol", "tools/sdk/sort.sol", "tools/elf-symbols.sol", "core/foreign.fpr",
              "core/trusted-modules.txt"
            ]
  links <- filter (\f -> "link-qosplug" `isPrefixOf` f && ".ld" `isSuffixOf` f) <$> listOr (home </> "qos/appside")
  mods <- concat <$> mapM (\d -> walk ".fpr" d) [home </> "std", home </> "programs/mods", root </> "std", root </> "core"]
  let files = fixed ++ map ((home </> "qos/appside") </>) (sort links) ++ mods
  lines' <- forM files $ \f -> do
    st <- try (getFileStatus f)
    pure $ case st of
      Left (_ :: IOException) -> f ++ "\0missing\n"
      Right s -> f ++ "\0" ++ show (modificationTimeHiRes s) ++ "\0" ++ show (fileSize s) ++ "\n"
  pure (BC.pack (concat lines'))

listOr :: FilePath -> IO [FilePath]
listOr d = listDirectory d `catch` \(_ :: IOException) -> pure []

-- every file with the suffix under d, sorted, depth first
walk :: String -> FilePath -> IO [FilePath]
walk suffix d = do
  names <- sort <$> listOr d
  fmap concat . forM names $ \n -> do
    let p = d </> n
    isDir <- doesDirectoryExist p
    isLink <- pathIsSymbolicLink p `catch` \(_ :: IOException) -> pure False
    if isDir && not isLink then walk suffix p else pure [p | suffix `isSuffixOf` n]

-- the last package built under each id, with what it was built from
type Packages = IORef (M.Map String (B.ByteString, B.ByteString))

packagePlugin :: Cfg -> Packages -> Int -> String -> B.ByteString -> IO B.ByteString
packagePlugin cfg packages slot plugid source = do
  fingerprint <- reachable cfg
  let key = B.concat [BC.pack (show slot ++ ":" ++ plugid ++ "\0"), source, BC.pack "\0", fingerprint]
  cached <- M.lookup plugid <$> readIORef packages
  case cached of
    Just (k, reply) | k == key -> pure reply
    _ -> do
      reply <- buildPlugin cfg plugid source
      modifyIORef' packages (if BC.pack "ok\n" `B.isPrefixOf` reply then M.insert plugid (key, reply) else M.delete plugid)
      pure reply

-- the package op, through qos-app.mk's plugin-qa target (one home for the unit
-- objects, link script and manifest mechanics); a stale package is removed
-- first, so a failed build never answers with an older .qa
buildPlugin :: Cfg -> String -> B.ByteString -> IO B.ByteString
buildPlugin cfg plugid source = do
  let b = cfBuild cfg
      src = b </> "fprd-src" </> (plugid ++ ".fpr")
      qa = b </> "fprd-packages" </> (plugid ++ ".qa")
  createDirectoryIfMissing True (takeDirectory src)
  createDirectoryIfMissing True (takeDirectory qa)
  B.writeFile src source
  removeIfExists qa
  r <- run cfg (cfHome cfg) 300 ["make", "-s", "plugin-qa", "PROG=" ++ src, "PLUG_OUT=" ++ qa, "BUILD=" ++ (b </> "fprd-objects")]
  built <- doesFileExist qa
  case r of
    Nothing -> pure (err "compile timed out")
    Just (Ran ExitSuccess _) | built -> okB <$> B.readFile qa
    Just (Ran _ o) -> pure (errB (diagnostics o "plugin build failed"))

removeIfExists :: FilePath -> IO ()
removeIfExists p = removeFile p `catch` \(e :: IOException) -> unless (isDoesNotExistError e) (throwIO e)

-- Publications serialize on a per-module writer lock, across daemon processes.
packageVersion :: Cfg -> String -> B.ByteString -> IO B.ByteString
packageVersion cfg plugid source = do
  let work = cfBuild cfg </> "fprd-versions" </> plugid
  createDirectoryIfMissing True work
  bracket (openFd (work </> ".writer.lock") WriteOnly (defaultFileFlags {creat = Just 0o600})) closeFd $ \fd -> do
    locked <- try (setLock fd (WriteLock, AbsoluteSeek, 0, 0))
    case locked of
      Left (_ :: IOException) -> pure (err "publication build busy")
      Right () -> packageVersionLocked cfg plugid source work

-- checked source version -> frozen blob -> complete .qa; no QOS writes
packageVersionLocked :: Cfg -> String -> B.ByteString -> FilePath -> IO B.ByteString
packageVersionLocked cfg plugid source work = do
  preferShippedDependencies cfg work
  let scratch = work </> (plugid ++ ".fpr")
  B.writeFile scratch source
  committed <- run cfg work 120 [cfCompiler cfg, "commit", scratch]
  case committed of
    Nothing -> pure (err "compile timed out")
    Just (Ran code o) | code /= ExitSuccess -> pure (errB (BC.strip o))
    Just _ -> do
      db <- readOr (work </> ".fpr/versions.db")
      let rows = [ws | l <- lines db, let ws = words l, length ws == 3, head ws == plugid]
      case listToMaybe (reverse rows) of
        Just [name, version, identity] | isIdentity identity -> do
          codegen <- firstNumberAfter "codegenRev = " <$> readOr (cfRoot cfg </> "compiler/Codegen.hs")
          abi <- firstNumberAfter "#define QOS_ABI_VERSION " <$> readOr (cfHome cfg </> "qos/appside/qos_abi.h")
          case (codegen, abi) of
            (Just cg, Just a) -> do
              let artifacts = work </> "packages" </> (Info.os ++ "-" ++ Info.arch ++ "-abi" ++ a ++ "-cg" ++ cg)
                  image = artifacts </> (identity ++ ".qa")
                  pending = artifacts </> (identity ++ ".pending.qa")
                  blob = work </> ".fpr/store" </> (identity ++ ".fpr")
              createDirectoryIfMissing True artifacts
              have <- doesFileExist image
              built <-
                if have
                  then pure Nothing
                  else
                    ( do
                        r <-
                          run cfg (cfHome cfg) 300
                            ["make", "-s", "plugin-qa", "PROG=" ++ blob, "PLUGID=" ++ plugid, "PLUG_OUT=" ++ pending, "BUILD=" ++ (work </> "objects")]
                        made <- doesFileExist pending
                        case r of
                          Nothing -> pure (Just (err "compile timed out"))
                          Just (Ran ExitSuccess _) | made -> renameFile pending image >> pure Nothing
                          Just (Ran _ o) ->
                            pure (Just (errB (let s = BC.strip o in if B.null s then BC.pack "plugin build failed" else s)))
                    )
                      `finally` removeIfExists pending
              case built of
                Just failure -> pure failure
                Nothing -> do
                  bytes <- B.readFile image
                  pure (okB (B.append (BC.pack (name ++ "\t" ++ version ++ "\t" ++ identity ++ "\n")) bytes))
            _ -> pure (err "cannot read the codegen revision or the QOS ABI version")
        _ -> pure (err "invalid committed publication binding")

isIdentity :: String -> Bool
isIdentity s = length s == 16 && all (\c -> isDigit c || (isHexDigit c && isLower c)) s

readOr :: FilePath -> IO String
readOr p = (BC.unpack <$> B.readFile p) `catch` \(_ :: IOException) -> pure ""

firstNumberAfter :: String -> String -> Maybe String
firstNumberAfter key text = go text
  where
    go [] = Nothing
    go s@(_ : rest)
      | key `isPrefixOf` s = case takeWhile isDigit (drop (length key) s) of
          [] -> go rest
          ds -> Just ds
      | otherwise = go rest

-- Commit closes a publication's tree by copying pinned dependencies; a local
-- copy would then shadow the shipped store, whose canonical path carries the
-- platform's library approval. Remove only byte-identical dependency copies;
-- publication roots and changed blobs stay, and nothing shared is written.
preferShippedDependencies :: Cfg -> FilePath -> IO ()
preferShippedDependencies cfg work = do
  db <- readOr (work </> ".fpr/versions.db")
  let roots = [ws !! 2 | l <- lines db, let ws = words l, length ws == 3]
      local = work </> ".fpr/store"
  forM_ [cfHome cfg, cfRoot cfg] $ \parent -> do
    shipped <- filter (".fpr" `isSuffixOf`) <$> listOr (parent </> ".fpr/store")
    forM_ shipped $ \name -> do
      let stem = dropExtension name
          candidate = local </> name
      unless (stem `elem` roots || not (isIdentity stem)) $ do
        isFile <- doesFileExist candidate
        isLink <- pathIsSymbolicLink candidate `catch` \(_ :: IOException) -> pure True
        when (isFile && not isLink) $ do
          a <- B.readFile candidate
          b <- B.readFile (parent </> ".fpr/store" </> name)
          when (a == b) (removeFile candidate)

-- a registered file, published when it changed since the caller's hash
type WatchCache = IORef (M.Map String (B.ByteString, B.ByteString))

watchVersion :: Cfg -> WatchCache -> String -> String -> IO B.ByteString
watchVersion cfg cache name known = case M.lookup name (cfWatches cfg) of
  Nothing -> pure (err "module is not registered for watching")
  Just path -> do
    source <- withFile path ReadMode (\h -> B.hGet h (maxRequest + 1))
    if B.length source > maxRequest
      then pure (err "watched source too large")
      else do
        cached <- M.lookup name <$> readIORef cache
        reply <- case cached of
          Just (s, r) | s == source -> pure r
          _ -> do
            r <- packageVersion cfg name source
            unless (r == err "publication build busy") (modifyIORef' cache (M.insert name (source, r)))
            pure r
        if BC.pack "ok\n" `B.isPrefixOf` reply
          then
            let header = BC.takeWhile (/= '\n') (B.drop 3 reply)
                fields = BC.split '\t' header
             in pure (if length fields > 2 && BC.unpack (fields !! 2) == known then BC.pack "ok\nsame\n" else reply)
          else pure reply

-- ---- request dispatch ------------------------------------------------------

data Request
  = Profile String
  | Check
  | Plugin Int String
  | Publication String
  | Watch String String
  | Unknown String

isId :: String -> Bool
isId (c : cs) = isLower c && length cs <= 15 && all (\x -> isLower x || isDigit x || x == '_') cs
isId [] = False

parseRequest :: String -> Request
parseRequest p
  | p `elem` ["qos-portable", "bare-metal"] = Profile p
  | p == "check" = Check
  | ["plugin", [s], i] <- splitOn ':' p, s >= '0', s <= '7', isId i = Plugin (fromEnum s - fromEnum '0') i
  | ["publication", i] <- splitOn ':' p, isId i = Publication i
  | ["watch", i, h] <- splitOn ':' p, isId i, h == "-" || isIdentity h = Watch i h
  | otherwise = Unknown p

splitOn :: Char -> String -> [String]
splitOn c s = case break (== c) s of
  (a, []) -> [a]
  (a, _ : rest) -> a : splitOn c rest

data State = State Packages WatchCache

answer :: Cfg -> State -> String -> B.ByteString -> IO B.ByteString
answer cfg (State packages watches) profile source = case parseRequest profile of
  Profile p -> compileProfile cfg p source
  Check -> checkSource cfg source
  Plugin slot i -> packagePlugin cfg packages slot i source
  Publication i -> packageVersion cfg i source
  Watch i h -> watchVersion cfg watches i h
  Unknown p ->
    pure (err ("unknown profile " ++ show p ++ " (want: bare-metal | qos-portable | check | plugin:<slot>:<id> | publication:<id> | watch:<id>:<hash>)"))

-- ---- the wire --------------------------------------------------------------

recvExact :: Socket -> Int -> IO B.ByteString
recvExact s n = go n []
  where
    go 0 acc = pure (B.concat (reverse acc))
    go k acc = do
      part <- NB.recv s (min k 65536)
      when (B.null part) (throwIO (userError "peer closed mid-frame"))
      go (k - B.length part) (part : acc)

le32 :: B.ByteString -> Int
le32 b = foldr (\i acc -> (acc `shiftL` 8) .|. fromIntegral (B.index b i)) 0 [0 .. 3]

frame :: B.ByteString -> B.ByteString
frame payload =
  let n = fromIntegral (B.length payload) :: Word32
   in B.append (B.pack [fromIntegral ((n `shiftR` k) .&. 0xff) | k <- [0, 8, 16, 24]]) payload

serveOne :: Cfg -> State -> Socket -> IO ()
serveOne cfg st c = do
  got <- timeout (connectionTimeout * 1000000) $ do
    n <- le32 <$> recvExact c 4
    if n > maxRequest then pure (Left ()) else Right <$> recvExact c n
  case got of
    Nothing -> hPutStrLn stderr "qos-fprd: connection dropped: no complete request in time"
    Just (Left ()) -> NB.sendAll c (frame (err "request too large"))
    Just (Right req) -> do
      let (p, rest) = BC.break (== '\n') req
          (profile, source) = if B.null rest then ("", B.empty) else (BC.unpack p, B.drop 1 rest)
      reply <-
        answer cfg st profile source `catches`
          [ Handler (\(e :: IOException) -> pure (err ("compiler service: " ++ show e))),
            Handler (\(e :: SomeException) -> case fromException e of
                        Just (ae :: AsyncException) -> throwIO ae
                        Nothing -> do
                          hPutStrLn stderr ("qos-fprd: request failed: " ++ show e)
                          pure (err "compiler service: internal error"))
          ]
      NB.sendAll c (frame reply)

-- Bind, refusing to replace anything but this user's own stale socket.
listenOn :: FilePath -> IO Socket
listenOn path = do
  existing <- try (getSymbolicLinkStatus path)
  uid <- getRealUserID
  case existing of
    Left (_ :: IOException) -> pure ()
    Right st -> do
      unless (isSocket st && fileOwner st == uid) $
        die ("qos-fprd: " ++ path ++ " exists and is not this user's socket; refusing to replace it")
      removeLink path
  s <- socket AF_UNIX Stream defaultProtocol
  old <- setFileCreationMask 0o177 -- the socket is created 0600: this user only
  bind s (SockAddrUnix path) `finally` setFileCreationMask old
  setFileMode path 0o600
  listen s 4
  pure s

daemon :: FilePath -> FilePath -> [(String, FilePath)] -> IO ()
daemon path work watches = do
  cfg <- configure work watches
  st <- State <$> newIORef M.empty <*> newIORef M.empty
  main' <- myThreadId
  stopping <- newIORef False
  let stop = Catch (writeIORef stopping True >> throwTo main' UserInterrupt)
  _ <- installHandler sigTERM stop Nothing
  _ <- installHandler sigINT stop Nothing
  _ <- installHandler sigPIPE Ignore Nothing
  s <- listenOn path
  pid <- getProcessID
  ready <- lookupEnv "QOSP_READY_FILE"
  forM_ ready $ \f -> writeFile f (show pid ++ "\n")
  hPutStrLn stderr ("qos-fprd: serving fpr on " ++ path ++ " pid=" ++ show pid) >> hFlush stderr
  let loop = do
        (c, _) <- accept s
        serveOne cfg st c `catch` (\(e :: IOException) -> hPutStrLn stderr ("qos-fprd: connection dropped: " ++ show e))
          `finally` close c
        loop
      finish = do
        readIORef (cfChild cfg) >>= killGroup
        close s `catch` \(_ :: IOException) -> pure ()
        removeLink path `catch` \(_ :: IOException) -> pure ()
  r <- try (loop `finally` finish)
  case r of
    Left UserInterrupt -> do
      administrative <- readIORef stopping
      if administrative then exitSuccess else exitWith (ExitFailure 130)
    Left e -> throwIO e
    Right () -> exitFailure

-- ---- client and selftest ---------------------------------------------------

request :: FilePath -> String -> B.ByteString -> IO B.ByteString
request path profile source = do
  s <- socket AF_UNIX Stream defaultProtocol
  flip finally (close s) $ do
    connect s (SockAddrUnix path)
    NB.sendAll s (frame (B.concat [BC.pack profile, BC.pack "\n", source]))
    r <- timeout (440 * 1000000) $ do
      n <- le32 <$> recvExact s 4
      when (n > 32 * 1024 * 1024) (throwIO (userError "compiler reply exceeds 32 MiB"))
      recvExact s n
    maybe (throwIO (userError "compiler reply timed out")) pure r

-- sha256 of a file by the platform's tool (selftest only)
sha256File :: FilePath -> IO String
sha256File f = do
  r <- try (readProcess "sha256sum" [f] "")
  case r of
    Right out -> pure (takeWhile (/= ' ') out)
    Left (_ :: IOException) -> takeWhile (/= ' ') <$> readProcess "shasum" ["-a", "256", f] ""

jsonString :: String -> String -> Maybe String
jsonString key text = case breakOn ("\"" ++ key ++ "\"") text of
  Nothing -> Nothing
  Just rest -> case dropWhile (`elem` " \t\n:") rest of
    '"' : v -> Just (takeWhile (/= '"') v)
    _ -> Nothing
  where
    breakOn k s
      | k `isPrefixOf` s = Just (drop (length k) s)
      | null s = Nothing
      | otherwise = breakOn k (tail s)

selftest :: IO ()
selftest = do
  sdk <- sdkRoot
  hash <- case sdk of
    Nothing -> pure Nothing
    Just root -> do
      manifest <- readFile (root </> "sdk.json")
      actual <- sha256File (root </> "fprisc/fpr")
      when (jsonString "compiler_sha256" manifest /= Just actual) (die "qos-fprd selftest: packaged compiler digest does not match SDK manifest")
      pure (Just actual)
  tmp <- getTemporaryDirectory
  pid <- getProcessID
  let dir = tmp </> ("qos-fprd-selftest-" ++ show pid)
  createDirectoryIfMissing True dir
  exe <- getExecutablePath
  let sock = dir </> "compiler.sock"
  logH <- openFile (dir </> "daemon.log") ReadWriteMode
  let cp = (proc exe ["daemon", "--socket", sock, "--work", dir]) {std_out = UseHandle logH, std_err = UseHandle logH, std_in = NoStream}
  outcome <- try $ bracket (createProcess cp) (\(_, _, _, ph) -> stopChild ph) $ \(_, _, _, ph) -> do
    awaitReady ph sock
    let source = BC.pack "A = use \"std/actor#201a0e9bf98a5154\".\nadd a b = a + b.\nmain = \"native Pi SDK\".\n"
        expect what ok reply = unless ok (throwIO (userError (what ++ ": " ++ BC.unpack (B.take 8192 reply))))
    checked <- request sock "check" source
    expect "check failed" (checked == BC.pack "ok\n") checked
    packaged <- request sock "plugin:0:sdkprobe" source
    expect "plugin failed" (BC.pack "ok\nQAR2\n" `B.isPrefixOf` packaged) packaged
    publication <- request sock "publication:sdkpub" source
    expect "publication failed" (BC.pack "ok\n" `B.isPrefixOf` publication) publication
    let (header, image) = BC.break (== '\n') (B.drop 3 publication)
        fields = BC.split '\t' header
    expect "invalid frozen publication"
      (length fields == 3 && head fields == BC.pack "sdkpub" && B.length (fields !! 2) == 16 && BC.pack "\nQAR2\n" `B.isPrefixOf` image) publication
    repeated <- request sock "publication:sdkpub" source
    expect "unchanged publication was not stable" (repeated == publication) repeated
    changed <- request sock "publication:sdkpub" (replaceOnce (BC.pack "a + b.") (BC.pack "a + b + 1.") source)
    expect "publication update failed" (BC.pack "ok\n" `B.isPrefixOf` changed) changed
    let (cheader, cimage) = BC.break (== '\n') (B.drop 3 changed)
        cfields = BC.split '\t' cheader
    expect "publication update lost immutable version identity"
      (take 2 cfields == [BC.pack "sdkpub", BC.pack "v1.1"] && length cfields == 3 && cfields !! 2 /= fields !! 2 && BC.pack "\nQAR2\n" `B.isPrefixOf` cimage) changed
    bad <- request sock "check" (BC.pack "main = syntax @@@.\n")
    expect "invalid source was accepted" (BC.pack "err\n" `B.isPrefixOf` bad) bad
    status <- stopChild ph
    unless (status == ExitSuccess) (throwIO (userError ("daemon did not stop cleanly: " ++ show status)))
    putStrLn $
      "{\"check\": \"ok\", \"plugin\": \"QAR2\", \"plugin_bytes\": " ++ show (B.length packaged - 3)
        ++ maybe "" (\h -> ", \"compiler_sha256\": \"" ++ h ++ "\"") hash
        ++ ", \"publication\": \"committed-frozen-stable-updated\", \"publication_version\": \"" ++ BC.unpack (cfields !! 1)
        ++ "\", \"invalid_source\": \"refused\", \"target\": \"" ++ pluginTarget ++ "\"}"
  hClose logH
  case outcome of
    Right () -> removePathForcibly dir
    Left (e :: SomeException) -> do
      logText <- readOr (dir </> "daemon.log")
      hPutStrLn stderr logText
      die ("qos-fprd selftest: " ++ show e ++ " (work kept in " ++ dir ++ ")")
  where
    replaceOnce old new s = let (a, b) = B.breakSubstring old s in if B.null b then s else B.concat [a, new, B.drop (B.length old) b]

-- probe with an unknown profile until the daemon answers it
awaitReady :: ProcessHandle -> FilePath -> IO ()
awaitReady ph sock = go (400 :: Int)
  where
    go 0 = throwIO (userError "compiler socket did not become ready")
    go k = do
      exited <- getProcessExitCode ph
      forM_ exited $ \c -> throwIO (userError ("compiler daemon exited: " ++ show c))
      r <- try (request sock "unknown" B.empty) :: IO (Either SomeException B.ByteString)
      case r of
        Right reply | BC.pack "err\nunknown profile" `B.isPrefixOf` reply -> pure ()
        _ -> threadDelay 50000 >> go (k - 1)

stopChild :: ProcessHandle -> IO ExitCode
stopChild ph = do
  st <- getProcessExitCode ph
  case st of
    Just c -> pure c
    Nothing -> do
      terminateProcess ph
      r <- timeout 5000000 (waitForProcess ph)
      case r of
        Just c -> pure c
        Nothing -> getPid ph >>= killGroupOne >> waitForProcess ph
  where
    killGroupOne Nothing = pure ()
    killGroupOne (Just p) = signalProcess sigKILL p `catch` \(_ :: IOException) -> pure ()

-- ---- main ----------------------------------------------------------------

data Opts = Opts {oSocket :: FilePath, oWork :: FilePath, oWatches :: [(String, FilePath)]}

parseDaemon :: Opts -> [String] -> Either String Opts
parseDaemon o args = case args of
  [] -> Right o {oWatches = reverse (oWatches o)}
  "--socket" : p : rest -> parseDaemon o {oSocket = p} rest
  "--work" : p : rest -> parseDaemon o {oWork = p} rest
  "--watch" : w : rest -> case break (== '=') w of
    (name, '=' : file)
      | not (isId name) || null file -> Left "watch registration must be ID=FILE (id: lowercase, at most 16 characters)"
      | name `elem` map fst (oWatches o) -> Left ("duplicate watched module " ++ name)
      | otherwise -> parseDaemon o {oWatches = (name, file) : oWatches o} rest
    _ -> Left "watch registration must be ID=FILE"
  other : _ -> Left ("unexpected argument " ++ other)

usage :: String
usage = "usage: qos-fprd daemon [--socket PATH] [--work DIR] [--watch ID=FILE]... | qos-fprd selftest | qos-fprd request [--socket PATH] PROFILE [FILE]"

clientRequest :: FilePath -> [String] -> IO ()
clientRequest sock args = case args of
  "--socket" : p : rest -> clientRequest p rest
  [profile] -> go profile B.empty
  [profile, file] -> B.readFile file >>= go profile
  _ -> hPutStrLn stderr usage >> exitWith (ExitFailure 2)
  where
    go profile source = do
      reply <- request sock profile source
      let (status, rest) = BC.break (== '\n') reply
      B.hPut stdout (B.drop 1 rest)
      hFlush stdout
      if status == BC.pack "ok" then exitSuccess else exitWith (ExitFailure 1)

main :: IO ()
main = do
  hSetBuffering stderr LineBuffering
  args <- getArgs
  sock <- fromMaybe "/tmp/fprd.sock" <$> lookupEnv "FPRD_SOCK"
  work <- fromMaybe "/run/fpr-sdk-work" <$> lookupEnv "FPRD_WORK"
  case args of
    "daemon" : rest -> case parseDaemon (Opts sock work []) rest of
      Left e -> hPutStrLn stderr (e ++ "\n" ++ usage) >> exitWith (ExitFailure 2)
      Right o -> daemon (oSocket o) (oWork o) (oWatches o)
    ["selftest"] -> selftest
    "request" : rest -> clientRequest sock rest
    ["--version"] -> putStrLn "qos-fprd (native compiler daemon, protocol of qos/portable/compile.c)"
    _ -> hPutStrLn stderr usage >> exitWith (ExitFailure 2)
