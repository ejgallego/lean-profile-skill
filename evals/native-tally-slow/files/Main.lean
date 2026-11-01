import Tally

open Tally

partial def run (h : Hist) (x : UInt64) (remaining buckets : Nat) : Hist :=
  if remaining == 0 then h
  else
    let x' := next x
    let bucket := ((x' >>> 33).toNat) % buckets
    run (h.record bucket) x' (remaining - 1) buckets

def main (args : List String) : IO UInt32 := do
  let samples := (args.getD 0 "200000").toNat!
  let buckets := (args.getD 1 "50000").toNat!
  let h := run (Hist.empty buckets samples) 42 samples buckets
  let (top, nonzero) := summarize h
  IO.println s!"samples={h.seen} top={top} nonzero={nonzero}"
  return 0
