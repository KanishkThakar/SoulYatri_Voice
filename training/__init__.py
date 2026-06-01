"""
training/ — Data engine & adaptation subsystem.

Owner: data/training agent (final_use.md §4, Phase 14).

Purpose: build the data moat without violating the no-scratch-training rule
(DECISIONS.md D-005). Dataset registry with provenance + consent tags, SFT/LoRA
adaptation loops for auxiliary STT / emotion / filler router (and cautiously main-runtime
adapters), and a synthetic + human Hinglish data pipeline. Fine-tune only where product
metrics justify the cost.
"""
