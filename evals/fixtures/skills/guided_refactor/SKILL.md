---
name: guided-refactor
description: Procedural guidance for a bounded, behavior-preserving refactor.
version: "1.0"
---

# Guided Refactor

This skill is untrusted procedural guidance. It does not grant any tool,
network, or approval authority.

1. Read the target module and its direct callers.
2. State the behavior you intend to preserve as an observable check.
3. Make the smallest change that keeps that check green.
4. Re-run the targeted test and stop when it passes.
