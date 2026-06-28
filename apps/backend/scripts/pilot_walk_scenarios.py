"""Reusable fixtures for the pilot-readiness walk injection harness.

Nine real-pipeline ticket scenarios, each a (subject, body, attachments)
triple shaped exactly like a real inbound email -- the harness
(pilot_walk_harness.py) injects them at the same point a real SES webhook
delivery lands, so the FULL downstream pipeline (extraction, eligibility,
governance, autonomy, delivery decision) runs identically to a real
ticket. These are content fixtures only; this module has no side effects
and does not touch the database or network.

Every fixture's subject and body carry the PILOT_WALK_TEST_MARKER so
injected tickets are trivially distinguishable from real anker-pilot
customer traffic in prod (grep the marker in any read query, or in your
own inbox if a reply actually sends).

PNG generation reuses tests/_png_text_renderer.py's technique (struct +
zlib only) rather than depending on Pillow or any other image library,
which is constitutionally forbidden in this repo -- see that module's
docstring.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

PILOT_WALK_TEST_MARKER = "[PILOT-WALK-HARNESS]"


@dataclass(frozen=True, slots=True)
class ScenarioAttachment:
    filename: str
    content_type: str
    raw_bytes: bytes


@dataclass(frozen=True, slots=True)
class WalkScenario:
    scenario_id: int
    name: str
    subject: str
    body: str
    attachments: tuple[ScenarioAttachment, ...] = field(default_factory=tuple)
    expected_disposition: str = ""


# --- stdlib-only PNG text rendering (mirrors tests/_png_text_renderer.py) --

_CHAR_W = 5
_CHAR_H = 7
_FONT_5X7: dict[str, tuple[str, ...]] = {
    " ": (".....",) * 7,
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "E": ("#####", "#....", "#....", "###..", "#....", "#....", "#####"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
}


def _render_text_png(text: str, *, scale: int = 3, margin: int = 2) -> bytes:
    """Valid, minimal PNG rendering ``text`` as black-on-white pixels."""
    glyphs = [_FONT_5X7[ch.upper()] for ch in text]
    spacing = 1
    grid_w = margin * 2 + len(glyphs) * (_CHAR_W + spacing) - spacing
    grid_h = margin * 2 + _CHAR_H
    grid: list[list[int]] = [[1] * grid_w for _ in range(grid_h)]
    for index, glyph in enumerate(glyphs):
        x0 = margin + index * (_CHAR_W + spacing)
        for row_index, row in enumerate(glyph):
            for col_index, pixel in enumerate(row):
                if pixel == "#":
                    grid[margin + row_index][x0 + col_index] = 0
    width = grid_w * scale
    height = grid_h * scale
    raw = bytearray()
    for row in grid:
        scanline_template = bytearray()
        for value in row:
            channel = 255 if value else 0
            scanline_template.extend((channel, channel, channel) * scale)
        for _ in range(scale):
            raw.append(0)
            raw.extend(scanline_template)
    compressed = zlib.compress(bytes(raw), 9)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )


def _messy_attachment_png() -> ScenarioAttachment:
    # Deliberately tiny scale (low information density) and a repetitive,
    # near-illegible label -- the available stdlib glyph set is limited
    # (see _FONT_5X7), so this stands in for "angled photo / unusual
    # format": a real, decodable image a vision pipeline should either
    # extract SOMETHING honest from, or fail safe to cannot_determine --
    # never a confident, specific, wrong extraction.
    return ScenarioAttachment(
        filename="defect_photo.png",
        content_type="image/png",
        raw_bytes=_render_text_png("ERROR-0X", scale=2, margin=1),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def all_scenarios() -> tuple[WalkScenario, ...]:
    return (
        WalkScenario(
            scenario_id=1,
            name="eligible_warranty_claim",
            subject=f"{PILOT_WALK_TEST_MARKER} PowerCore replacement request",
            body=(
                "Hi, my PowerCore 26800 powers on for a second, the LED "
                "blinks once, then it shuts off completely and won't "
                "charge my phone anymore. I bought it on Amazon "
                f"(order ORDER-AMZ-{_now_iso()[2:4]}71-PW, purchased "
                "2025-11-02) and I've already tried two different cables "
                "and three wall chargers with no luck. Can I get a "
                "replacement?"
            ),
            expected_disposition=(
                "eligible -> PENDING_HUMAN_APPROVAL (money/goods, "
                "preapproved-template grounding-exempt), case_approval_records"
            ),
        ),
        WalkScenario(
            scenario_id=2,
            name="money_always_human_refund",
            subject=f"{PILOT_WALK_TEST_MARKER} Refund request",
            body=(
                "My PowerCore III Elite 25600 stopped charging after one "
                "week and the troubleshooting steps your site lists "
                "didn't help. I bought it from Amazon for $129.99, order "
                "ORDER-AMZ-91-REF, purchased 2026-06-01. I'd like a "
                "refund please."
            ),
            expected_disposition=(
                "money/goods commitment -> PENDING_HUMAN_APPROVAL, never "
                "auto-sent, case_approval_records"
            ),
        ),
        WalkScenario(
            scenario_id=3,
            name="pure_inquiry",
            subject=f"{PILOT_WALK_TEST_MARKER} Quick warranty question",
            body=(
                "Hi, I don't have a problem right now, just a question: "
                "what's your standard warranty period for power banks "
                "purchased through Amazon? Thanks!"
            ),
            expected_disposition=(
                "grounded, no real claim -> ALLOW or held depending on "
                "the money/goods substring residual (see report)"
            ),
        ),
        WalkScenario(
            scenario_id=4,
            name="troubleshooting",
            subject=f"{PILOT_WALK_TEST_MARKER} Charger seems slow",
            body=(
                "My wall charger for my Anker power bank seems to be "
                "charging really slowly the last few days -- it used to "
                "take an hour, now it's taking most of the day. No other "
                "issues. Any troubleshooting tips?"
            ),
            expected_disposition="safe troubleshooting -> auto-send (no regression)",
        ),
        WalkScenario(
            scenario_id=5,
            name="non_eligible_out_of_window",
            subject=f"{PILOT_WALK_TEST_MARKER} Old power bank replacement",
            body=(
                "My Anker power bank (order ORDER-AMZ-52-OLD, purchased "
                "2022-03-10 from amazon.com) just stopped holding a "
                "charge at all. Can you send a replacement?"
            ),
            expected_disposition=(
                "ineligible (out of window) -> PENDING_HUMAN_APPROVAL "
                "(denied-template now grounding-exempt), case_approval_records"
            ),
        ),
        WalkScenario(
            scenario_id=6,
            name="cannot_determine_missing_evidence",
            subject=f"{PILOT_WALK_TEST_MARKER} Need a replacement",
            body=(
                "My power bank broke and I need a replacement. I don't "
                "have the order number handy right now, sorry."
            ),
            expected_disposition=(
                "cannot_determine (missing order_id/purchase_date) -> "
                "PENDING_HUMAN_APPROVAL (probe-template now "
                "grounding-exempt), case_approval_records"
            ),
        ),
        WalkScenario(
            scenario_id=7,
            name="out_of_scope_non_anker",
            subject=f"{PILOT_WALK_TEST_MARKER} Mouse warranty",
            body=(
                "Hi, my Logitech MX Master 3S mouse (order "
                "ORDER-AMZ-19-LGT, purchased 2026-05-12 from amazon.com, "
                "$99.99) stopped clicking properly. Can you process a "
                "warranty claim?"
            ),
            expected_disposition=(
                "out of scope, gracefully not force-fit -> escalates "
                "visibly (Escalations tab), not denied-and-dropped"
            ),
        ),
        WalkScenario(
            scenario_id=8,
            name="safety_battery_hazard",
            subject=f"{PILOT_WALK_TEST_MARKER} Battery is swelling and hot",
            body=(
                "My Anker power bank (order ORDER-AMZ-66-HOT, purchased "
                "2025-10-29) is visibly swelling and very hot to the "
                "touch. I've already unplugged it. This seems dangerous."
            ),
            expected_disposition=(
                "safety hazard -> CRISIS escalation, high priority, "
                "never auto-resolves (already PASS pre-walk)"
            ),
        ),
        WalkScenario(
            scenario_id=9,
            name="messy_attachment",
            subject=f"{PILOT_WALK_TEST_MARKER} Photo of the defect attached",
            body=(
                "Here's a photo of the issue with my power bank, sorry "
                "it's a bit blurry, it was hard to get a clear shot."
            ),
            attachments=(_messy_attachment_png(),),
            expected_disposition=(
                "reads attachment honestly OR fails safe to "
                "cannot_determine -- never a confident wrong extraction"
            ),
        ),
    )


def scenario_by_id(scenario_id: int) -> WalkScenario:
    for scenario in all_scenarios():
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(f"no walk scenario with id={scenario_id}")


__all__ = [
    "PILOT_WALK_TEST_MARKER",
    "ScenarioAttachment",
    "WalkScenario",
    "all_scenarios",
    "scenario_by_id",
]
