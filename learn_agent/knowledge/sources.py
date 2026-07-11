from __future__ import annotations
"""
Source directories and category mapping for the AI Learning Agent.
Add new directories here to expand the knowledge base.
"""
from pathlib import Path

BOOK_SOURCES = [
    {
        "path": Path("/Users/vaibhavgupta/Desktop/Agentic AI"),
        "category": "Agentic AI",
        "recurse": False,   # top-level books only (not sub-dirs)
        "max_pages": 120,
        "priority": "high",
    },
    {
        "path": Path("/Users/vaibhavgupta/Desktop/Agentic AI/Research Papers - AI Agents"),
        "category": "Research Papers",
        "recurse": False,
        "max_pages": 60,
        "priority": "high",
    },
    {
        "path": Path("/Users/vaibhavgupta/Desktop/Agentic AI/Vibe Coding"),
        "category": "Vibe Coding",
        "recurse": False,
        "max_pages": 80,
        "priority": "medium",
    },
    {
        "path": Path("/Users/vaibhavgupta/Desktop/AI"),
        "category": "AI & ML",
        "recurse": False,
        "max_pages": 80,
        "priority": "medium",
    },
    {
        "path": Path("/Users/vaibhavgupta/Desktop/AI/Applied AI in Finance"),
        "category": "AI in Finance",
        "recurse": False,
        "max_pages": 60,
        "priority": "medium",
    },
    {
        "path": Path("/Users/vaibhavgupta/Desktop/AI/AI in Healthcare"),
        "category": "AI in Healthcare",
        "recurse": False,
        "max_pages": 60,
        "priority": "medium",
    },
    {
        "path": Path("/Users/vaibhavgupta/Desktop/AI/Quantum Computing"),
        "category": "Quantum Computing",
        "recurse": False,
        "max_pages": 60,
        "priority": "medium",
    },
]

CATEGORY_COLORS = {
    "Agentic AI":       "#6366f1",
    "Research Papers":  "#f59e0b",
    "Vibe Coding":      "#22c55e",
    "AI & ML":          "#3b82f6",
    "AI in Finance":    "#10b981",
    "AI in Healthcare": "#ef4444",
    "Quantum Computing":"#8b5cf6",
}
