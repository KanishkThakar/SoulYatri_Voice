"""
aux/text_brain/prompts.py — Prompt templates for the auxiliary text brain
=========================================================================
Centralized, versioned prompt builders for each :class:`TextBrainTask`.

Kept separate from ``service.py`` so prompts can be reviewed, tested, and tuned
without touching client/serving logic. All prompts make the auxiliary role
explicit: this brain supports memory/safety/tools/RAG/labeling — it never acts as
the primary conversational voice.
"""

from __future__ import annotations

from auxiliary.text_brain.contracts import TextBrainRequest, TextBrainTask, ToolSpec

PROMPT_VERSION = "v1"

# Shared system framing — reused across tasks.
AUX_SYSTEM_PROMPT = (
    "You are SoulYatri's AUXILIARY text brain. You support memory compression, "
    "tool planning, moderation summaries, RAG query preparation, transcript cleanup, "
    "and dataset labeling. You are NOT the primary conversational voice; never produce "
    "spoken replies to the end user. Be concise, structured, and deterministic. "
    "Always return only what the task asks for."
)


def _tool_catalog(tools: list[ToolSpec]) -> str:
    lines = []
    for t in tools:
        params = ", ".join(f"{p.name}:{p.type}" for p in t.params) or "(none)"
        lines.append(f"- {t.name}({params}) — {t.description} [safe={t.safe}]")
    return "\n".join(lines) if lines else "(no tools available)"


def build_messages(req: TextBrainRequest, tools: list[ToolSpec]) -> list[dict]:
    """Build an Ollama-style chat ``messages`` list for the request.

    Returns a list of ``{"role", "content"}`` dicts. The system prompt is always
    first; the user content is task-specialized.
    """
    user = _build_user_content(req, tools)
    return [
        {"role": "system", "content": AUX_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _build_user_content(req: TextBrainRequest, tools: list[ToolSpec]) -> str:
    task = req.task
    payload = req.payload

    if task is TextBrainTask.memory_summary:
        turns = payload.get("turns", [])
        joined = "\n".join(f"- {t}" for t in turns)
        return (
            "TASK: memory_summary\n"
            "Compress the following conversation turns into 1-2 sentences capturing "
            "durable facts, preferences, and emotional context. Output plain text only.\n\n"
            f"TURNS:\n{joined}"
        )

    if task is TextBrainTask.tool_plan:
        query = payload.get("query", "")
        return (
            "TASK: tool_plan\n"
            "Decide which (if any) of the available tools to call to satisfy the request. "
            'Output a JSON array of {"tool", "arguments", "reason"}. Empty array if '
            "no tool is needed. Only use listed tools.\n\n"
            f"AVAILABLE TOOLS:\n{_tool_catalog(tools)}\n\n"
            f"REQUEST: {query}"
        )

    if task is TextBrainTask.moderation_summary:
        events = payload.get("events", [])
        joined = "\n".join(f"- {e}" for e in events)
        return (
            "TASK: moderation_summary\n"
            "Summarize the moderation-relevant signals below for human review in <=2 "
            "sentences. Note any self-harm, abuse, or escalation cues. Plain text only.\n\n"
            f"EVENTS:\n{joined}"
        )

    if task is TextBrainTask.rag_query:
        utterance = payload.get("utterance", "")
        return (
            "TASK: rag_query\n"
            "Produce up to 3 concise retrieval queries (one per line) that would fetch "
            "context useful for answering the user utterance. No commentary.\n\n"
            f"UTTERANCE: {utterance}"
        )

    if task is TextBrainTask.transcript_cleanup:
        raw = payload.get("text", "")
        return (
            "TASK: transcript_cleanup\n"
            "Lightly clean the transcript: fix obvious ASR artifacts, capitalization, and "
            "punctuation. Preserve meaning and code-switching (Hindi/English/Hinglish). "
            "Output only the cleaned text.\n\n"
            f"TRANSCRIPT: {raw}"
        )

    if task is TextBrainTask.dataset_label:
        sample = payload.get("text", "")
        label_space = payload.get("labels", ["warm_ack", "question", "distress", "smalltalk"])
        return (
            "TASK: dataset_label\n"
            f"Choose the best label(s) from {label_space} for the sample. Output a JSON "
            "array of label strings.\n\n"
            f"SAMPLE: {sample}"
        )

    # Defensive default — should be unreachable given the enum.
    return f"TASK: {task.value}\nPAYLOAD: {payload}"
