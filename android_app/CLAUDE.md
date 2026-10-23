# App UI rules
- Trace: custom Canvas, ECG paper grid (1 mm / 5 mm, 25 mm/s, 10 mm/mV, scaled by DPI), sweep with erase bar. No chart libraries.
- Main screen: trace, HR, quality state. Nothing else. Diagnostics live on a separate research screen.
- HR: shown only on GOOD; otherwise "—" plus the likely cause and a fix in one line.
- RMSSD: hidden unless research mode is on; labelled "experimental".
- Theme: dark, one accent colour for the trace, red reserved for alerts. Tabular digits for all numbers.
- Never use colour alone to show state. No emoji, no gradients.
- Before claiming a UI change is done: render it (Roborazzi or adb screencap), look at the screenshot, fix what's off.
- Design work uses replay mode with captures/ files, never synthetic sine waves.
