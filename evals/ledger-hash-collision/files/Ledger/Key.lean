namespace Ledger

/-- An account is identified by its region and its number within the region.
Account numbers are handed out in blocks of 65536 per region. -/
structure AccountKey where
  region : UInt8
  account : UInt32
  deriving BEq, Repr, Inhabited

instance : Hashable AccountKey where
  hash k := mixHash (hash k.region) (hash (k.account >>> 16))

def AccountKey.lt (a b : AccountKey) : Bool :=
  a.region < b.region || (a.region == b.region && a.account < b.account)

end Ledger
