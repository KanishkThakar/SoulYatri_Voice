"""
safety/ — Safety, consent, anti-cloning, and watermarking subsystem.

Owner: safety agent (final_use.md §4, Phase 11).

Purpose: a first-class gate (not a post-process). Moderation + crisis/self-harm
escalation, consent-first voice policy with a protected-voice list and admin review, and
synthesized-audio watermarking. Implements VoiceRequest and ModerationDecision from
shared/contracts.py. Fail-closed by default (DECISIONS.md D-007).
"""
