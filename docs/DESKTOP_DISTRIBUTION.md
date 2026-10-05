# Windows app: distribution, antivirus and "Windows protected your PC"

Honest status, 5 Oct 2026.

## Why V3's agent was flagged
Windows SmartScreen and antivirus judge two things: **who signed the file** and **how many people already run it**. An unsigned, brand-new program fails both, whatever it contains. V3 also used PyInstaller, a packer that malware commonly uses, so many antivirus engines flag every PyInstaller file by habit.

## What V4 already does to look less suspicious
- Native C#/.NET app, not PyInstaller. No packer, no obfuscation, no single-file self-extractor.
- Runs as a normal user, never asks for administrator rights (`app.manifest`).
- Publisher/author metadata: Suraj Pandavula (assembly Authors and Company).
- Secrets are protected with Windows DPAPI; data lives in `%LOCALAPPDATA%\AutoPrintV4`, separate from V3.

## What cannot be fixed with code
**Putting your name in the file properties does not remove the warning.** Only a code-signing certificate does, and even then SmartScreen reputation builds slowly.

| Option | Cost | Result |
|---|---|---|
| Unsigned, shopkeeper clicks "More info, Run anyway" | free | Fine for the private pilot with a few shops you visit. Write this step into the runbook |
| Report the file to Microsoft as a false positive (Defender submission portal) | free | Usually clears Defender within days; repeat per release |
| SignPath Foundation (free signing for open-source projects) | free | Needs a public repo and an OSS licence; verify eligibility before relying on it |
| Individual code-signing certificate | paid (about USD 100-400 per year) | Removes "unknown publisher"; SmartScreen still warms up over time |
| Microsoft Store (MSIX) | one-time registration fee | Store installs skip SmartScreen; not verified for this app, needs a check |

Recommendation: unsigned for the first pilot shops (installed by you in person), submit each release to Microsoft, and buy a certificate once shops install without you. Not yet verified: whether the current build triggers any antivirus; test with Defender and upload to a multi-engine scanner before handing it out.

## Distribution rules
- Give the file only from the official V4 link, with its SHA-256 printed next to it.
- SumatraPDF (GPL-3.0) ships as a separate program in `tools/`; include its licence and source link. Its hash is checked before every print.
