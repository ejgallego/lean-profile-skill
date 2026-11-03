---
type: llm
focus: trace
weight: 1
---

The result identifies the Hashable AccountKey instance as the cause: hashing only the account's high bits leaves a handful of distinct hashes, so the map degenerates into long chains. Saying only that the HashMap is slow does not pass.
