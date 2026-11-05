"""One colour palette for Excel, PDF and the e-mail page.

Rules (agreed with the bank users): no pure red and no yellow anywhere.
  teal / green  = good (Submitted, Done, Within SLA, In)
  soft orange   = not good (Incomplete, Due, SLA breach)  - calm, never alarming
  indigo        = Out area
  light sky-blue = "please check" cell in the INTERNAL copy only
"""
NAVY = "1F3A5F"
NAVY_DARK = "14284A"
TEXT = "1E293B"
MUTED = "64748B"
BORDER = "CBD5E1"
ZEBRA = "F8FAFC"
WHITE = "FFFFFF"
PANEL = "F1F5F9"        # KPI tiles, soft panels

POS = "047857"          # good: Submitted, Done, Within SLA
POS_BG = "D1FAE5"
NEG = "B45309"          # not good: Incomplete, Due, SLA breach  (burnt orange text)
NEG_BG = "FDE8D3"       # soft peach (never yellow)
OUT = "4338CA"          # area Out (indigo)
OUT_BG = "E0E7FF"
IN = "0F766E"           # area In (teal)
IN_BG = "CCFBF1"

NOTE = "B45309"         # a problem written in brackets inside Done
HILITE = "9A3412"       # a problem repeated in Due: text ...
HILITE_BG = "FBDCC0"    # ... on a soft peach marker (like a highlighter, easy on the eyes)
DUE_CELL_BG = "FFF4EA"  # very pale peach tint of a Report Summary cell that has Due items

BAND_OK_BG, BAND_OK_TX = "D1FAE5", "065F46"
BAND_NO_BG, BAND_NO_TX = "FDE8D3", "9A3412"

KIND_BG = {"Package": "EEF2F7", "Single": "F3F4F6", "ReCpv": "FFF0E3", "Extra": "F1ECFA"}
KIND_TX = {"Package": "1D4ED8", "Single": "475569", "ReCpv": "C2410C", "Extra": "6D28D9"}
CHECK = "BFE3FF"        # internal copy only: light sky-blue = "please check this cell"
