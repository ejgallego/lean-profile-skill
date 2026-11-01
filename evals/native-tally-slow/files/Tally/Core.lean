namespace Tally

/-- Rolling histogram over a fixed number of buckets. -/
structure Hist where
  counts : Array Nat
  seen   : Nat
  limit  : Nat
  deriving Inhabited

def Hist.empty (buckets limit : Nat) : Hist :=
  { counts := Array.replicate buckets 0, seen := 0, limit }

/-- Record one sample. Past `limit` the histogram is frozen. -/
def Hist.record (h : Hist) (bucket : Nat) : Hist :=
  let counts := h.counts.modify bucket (· + 1)
  if h.seen < h.limit then
    { h with counts, seen := h.seen + 1 }
  else
    h

/-- Deterministic linear congruential sample stream. -/
def next (x : UInt64) : UInt64 :=
  x * 6364136223846793005 + 1442695040888963407

def summarize (h : Hist) : Nat × Nat :=
  let top := h.counts.foldl max 0
  let nonzero := h.counts.foldl (fun acc c => if c > 0 then acc + 1 else acc) 0
  (top, nonzero)

end Tally
