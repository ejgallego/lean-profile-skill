import Ledger

def main (args : List String) : IO UInt32 := do
  let (n, accounts) := match args with
    | [n] => (n.toNat!, 12000)
    | [n, a] => (n.toNat!, a.toNat!)
    | _ => (150000, 12000)
  IO.println (Ledger.run n accounts)
  return 0
