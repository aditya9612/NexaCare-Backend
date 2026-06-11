"""
app/agent/graph.py
------------------
LangGraph state machine for NexaCare AI Appointment Agent.

The graph is used primarily for:
  1. State schema enforcement (BookingCallState TypedDict)
  2. Valid step transition enforcement
  3. Future: parallel tool calls, memory, persistence

Note: Because Twilio drives the flow via webhooks (one HTTP request
per turn), we don't run the graph as a blocking stream. Instead,
each webhook handler calls the appropriate node function directly
and stores the updated state in session_store. The graph provides
the schema and transition validation layer.

Call flow:
  language_select → greeting → service_menu
                                    │
                              (press 1: book)
                                    │
                          collect_name → collect_problem
                                              │
                                       analyse_symptoms
                                              │
                                       suggest_doctors → select_doctor
                                                               │
                                                         select_slot
                                                               │
                                                           confirm
                                                               │
                                                           booked → END
"""

from langgraph.graph import StateGraph, END
from app.agent.state import BookingCallState


def build_graph():
    """Build and compile the appointment booking state graph."""
    builder = StateGraph(BookingCallState)

    # ── Register all nodes ─────────────────────────────────────────────────
    # Each is a passthrough lambda — actual logic lives in nodes/*.py
    # called from router.py per Twilio webhook.
    for node_name in [
        "language_select",
        "greeting",
        "service_menu",
        "collect_name",
        "collect_problem",
        "suggest_doctors",
        "select_doctor",
        "select_slot",
        "confirm",
        "booked",
        "error",
    ]:
        builder.add_node(node_name, lambda s: s)

    # ── Entry point ────────────────────────────────────────────────────────
    builder.set_entry_point("language_select")

    # ── Edges: define valid transitions ────────────────────────────────────
    builder.add_edge("language_select", "greeting")
    builder.add_edge("greeting",        "service_menu")
    builder.add_edge("service_menu",    "collect_name")
    builder.add_edge("collect_name",    "collect_problem")
    builder.add_edge("collect_problem", "suggest_doctors")
    builder.add_edge("suggest_doctors", "select_doctor")
    builder.add_edge("select_doctor",   "select_slot")
    builder.add_edge("select_slot",     "confirm")
    builder.add_edge("confirm",         "booked")
    builder.add_edge("booked",          END)
    builder.add_edge("error",           END)

    return builder.compile()


# Compile once at import time — reused for all calls
appointment_graph = build_graph()