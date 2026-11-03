import Ledger.Book

namespace Ledger

def fmtCents (c : Int) : String :=
  let sign := if c < 0 then "-" else ""
  let a := c.natAbs
  let cents := a % 100
  sign ++ toString (a / 100) ++ "." ++ (if cents < 10 then "0" else "") ++ toString cents

def report (b : Book) : String := Id.run do
  let entries := b.balances.toArray.qsort fun (k₁, v₁) (k₂, v₂) =>
    v₁ > v₂ || (v₁ == v₂ && k₁.lt k₂)
  let mut lines := #[
    s!"postings: {b.postings}",
    s!"accounts: {entries.size}"]
  for i in [0:4] do
    lines := lines.push s!"region {i}: {fmtCents b.regionTotals[i]!}"
  lines := lines.push "top accounts:"
  for (k, v) in entries.extract 0 5 do
    lines := lines.push s!"  r{k.region}/{k.account}: {fmtCents v}"
  let checksum := entries.foldl (init := (0 : Nat)) fun acc (k, v) =>
    (acc * 31 + k.region.toNat * 1000003 + k.account.toNat + v.natAbs) % 1000000007
  lines := lines.push s!"checksum: {checksum}"
  return "\n".intercalate lines.toList

def run (n accounts : Nat) : String :=
  report (Book.ofTxns (genTxns n accounts))

end Ledger
