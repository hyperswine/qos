-- The Pi SDK only serves fprd's AOT and immutable-source operations. Reuse
-- the exact FP-RISC frontend/code generator without linking the separate Sol
-- VM's graphics, Git and archive runtime into this appliance build tool.
module PiEditorCompiler (main) where

import qualified Compile
import qualified Commit
import GHC.IO.Encoding (setLocaleEncoding, utf8)
import System.Environment (getArgs, withArgs)
import System.Exit (exitFailure)
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
    (a : _) | not (null a) && (head a == '-' || '/' `elem` a || '.' `elem` a) ->
      withArgs args Compile.compileMain
    _ -> do
      hPutStrLn stderr "Pi Editor SDK: compile [flags] in.fpr out.s | commit file.fpr | versions"
      exitFailure
