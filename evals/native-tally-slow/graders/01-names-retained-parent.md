---
type: llm
focus: trace
weight: 1
---

The result identifies that the array copy happens because the old Hist is still live at the update in Hist.record, not merely that the array is copied.
