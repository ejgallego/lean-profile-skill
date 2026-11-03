import Ledger.Key

namespace Ledger

structure Txn where
  key : AccountKey
  day : UInt16
  amount : Int
  deriving Inhabited

/-- Deterministic linear congruential generator, so runs are reproducible. -/
structure Rng where
  state : UInt64

def Rng.next (r : Rng) : UInt64 × Rng :=
  let s := r.state * 6364136223846793005 + 1442695040888963407
  (s >>> 33, ⟨s⟩)

def genTxns (n : Nat) (accounts : Nat) (seed : UInt64 := 42) : Array Txn := Id.run do
  let mut r : Rng := ⟨seed⟩
  let mut out : Array Txn := Array.mkEmpty n
  for _ in [0:n] do
    let (a, r1) := r.next
    let (b, r2) := r1.next
    let (c, r3) := r2.next
    r := r3
    let region := (a % 4).toUInt8
    let account := (b % accounts.toUInt64).toUInt32
    let cents : Int := (c % 200001).toNat
    let amount := cents - 100000
    out := out.push { key := ⟨region, account⟩, day := ((a >>> 8) % 365).toUInt16, amount }
  return out

end Ledger
