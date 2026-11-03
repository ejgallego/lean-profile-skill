import Std.Data.HashMap
import Ledger.Gen

namespace Ledger

structure Book where
  balances : Std.HashMap AccountKey Int := {}
  regionTotals : Array Int := Array.replicate 4 0
  postings : Nat := 0

def Book.post (b : Book) (t : Txn) : Book :=
  let balances := b.balances.alter t.key fun
    | none => some t.amount
    | some v => some (v + t.amount)
  let i := t.key.region.toNat
  { balances
    regionTotals := b.regionTotals.modify i (· + t.amount)
    postings := b.postings + 1 }

def Book.ofTxns (ts : Array Txn) : Book :=
  ts.foldl Book.post {}

end Ledger
