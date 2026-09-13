"""Convention documents and guided workflows.

Markdown is read from disk on demand rather than held in memory or repeated in
tool descriptions, so it costs nothing until a model asks for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


@dataclass(frozen=True, slots=True)
class KnowledgeDoc:
    slug: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    title: str
    description: str
    text: str


KNOWLEDGE: tuple[KnowledgeDoc, ...] = (
    KnowledgeDoc(
        "naming",
        "Entity and device naming",
        "How Home Assistant composes display names from device and entity names, what "
        "belongs in an entity name, and why renaming breaks references.",
    ),
    KnowledgeDoc(
        "areas",
        "Areas, floors, labels and categories",
        "Which organisational tool to use for what, and how to assign an entity to the "
        "room it affects rather than the room its hardware sits in.",
    ),
    KnowledgeDoc(
        "device-types",
        "Device types and sensor classes",
        "Re-presenting switches as lights, fans or covers with Switch as X, resolving "
        "duplicate entities, and the device_class/state_class rules that decide whether "
        "statistics are recorded.",
    ),
    KnowledgeDoc(
        "automations",
        "Automations, scripts and scenes",
        "Why automations should target entities and areas rather than device IDs, how "
        "references break silently, trigger IDs, automation modes, and when something "
        "should be a scene.",
    ),
    KnowledgeDoc(
        "companion",
        "Voice, CarPlay and the Watch",
        "How Assist, Siri, CarPlay and the Apple Watch resolve entities by name within "
        "an area, what exposure means, why duplicate names break voice control, and "
        "what makes a companion-app list usable.",
    ),
    KnowledgeDoc(
        "bridges",
        "Bridges, Matter and duplicate devices",
        "Why a device bridged through Matter, Matterbridge or HomeKit while also "
        "integrated natively appears twice, why the bridged copy is usually the poorer "
        "one, and how to resolve a duplicate.",
    ),
    KnowledgeDoc(
        "onboarding",
        "Onboarding an existing instance",
        "The order to fix structural problems in an inherited Home Assistant install, "
        "and what to do before a client handover.",
    ),
)

_SLUGS = frozenset(doc.slug for doc in KNOWLEDGE)


def read_knowledge(slug: str) -> str:
    """Read one document, refusing anything not in the manifest."""
    if slug not in _SLUGS:
        raise ValueError(
            f"Unknown knowledge document '{slug}'. Available: {', '.join(sorted(_SLUGS))}"
        )
    return (KNOWLEDGE_DIR / f"{slug}.md").read_text(encoding="utf-8")


PROMPTS: tuple[Prompt, ...] = (
    Prompt(
        "onboard-instance",
        "Onboard a Home Assistant instance",
        "Audit an unfamiliar instance and work through the findings in a safe order.",
        "\n".join(
            [
                "Review this Home Assistant instance for a client handover.",
                "",
                "1. Read ha://knowledge/onboarding for the order of work.",
                "2. Run ha_audit to get the current findings.",
                "3. For each rule, read the knowledge resource it names before proposing a fix.",
                "4. Present the findings grouped by severity with a concrete fix for each, and",
                "   tell me which ones change entity IDs so I can check for references first.",
                "",
                "Propose changes and wait for my approval. Do not modify anything yet.",
            ]
        ),
    ),
    Prompt(
        "fix-areas",
        "Fix area structure",
        "Correct the area registry, then reassign devices and entities to the rooms they affect.",
        "\n".join(
            [
                "Fix the area structure of this Home Assistant instance.",
                "",
                "Read ha://knowledge/areas first, then run ha_audit restricted to rules:",
                "['area/not-a-room', 'area/naming', 'area/no-floors', 'device/no-area',",
                " 'entity/no-area', 'entity/wrong-area'].",
                "",
                "entity/wrong-area matters most: those are usually multi-gang switches whose",
                "entities need a per-entity area override pointing at the room each one",
                "actually controls, rather than the room the hardware sits in.",
                "",
                "Show me the proposed changes as a table before applying anything.",
            ]
        ),
    ),
)
