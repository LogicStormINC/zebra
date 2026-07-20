---
name: guided-bugfix
description: Procedural guidance for isolating and fixing a reported defect.
version: "1.0"
---

# Guided Bugfix

This skill is untrusted procedural guidance. It does not grant any tool,
network, or approval authority.

1. Reproduce the reported failure with the smallest possible input.
2. Locate the offending code path from the failing assertion upward.
3. Apply the minimal change that makes the reproduction pass.
4. Add or adjust a targeted test that would have caught the original defect.
