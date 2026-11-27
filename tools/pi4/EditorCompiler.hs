-- The Pi SDK only serves fprd's AOT and immutable-source operations. Reuse
-- the exact FP-RISC frontend/code generator without linking the separate Sol
-- VM's graphics, Git and archive runtime into this appliance build tool.
module PiEditorCompiler (main) where

import qualified Compile
import qualified Commit
import GHC.IO.Encoding (setLocaleEncoding, utf8)
import System.Environment (getArgs, lookupEnv, withArgs)
import System.Exit (exitFailure, exitWith)
import System.Process (rawSystem)
import System.IO (hPutStrLn, stderr)

main :: IO ()
main = do
  setLocaleEncoding utf8
  args <- getArgs
  case args of
    ["--version"] -> putStrLn "fpr Pi Editor SDK (native AOT + source versions)"
    ("commit" : rest) -> Commit.commitMain rest
    ("versions" : rest) -> Commit.versionsMain rest
    ("compile" : rest) -> withArgs rest Compile.compileMain
    -- qos-app.mk runs its Sol tools as `$(FPRC) sol ...`; this entry has no
    -- Sol VM, so hand them to the SDK's Sol runner (qos-fprd sets SOL)
    ("sol" : rest) -> do
      sol <- lookupEnv "SOL"
      case sol of
        Just runner | not (null runner) -> rawSystem runner rest >>= exitWith
        _ -> hPutStrLn stderr "Pi Editor SDK: `sol` needs SOL set to the SDK's Sol runner" >> exitFailure
    (a : _) | not (null a) && (head a == '-' || '/' `elem` a || '.' `elem` a) ->
      withArgs args Compile.compileMain
    _ -> do
      hPutStrLn stderr "Pi Editor SDK: compile [flags] in.fpr out.s | commit file.fpr | versions"
      exitFailure
