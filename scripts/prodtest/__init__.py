"""Production black-box test harness.

See scripts/prodtest/README.md for the full explanation. Short version:
every probe in probes/ exercises a real flow against the real running
production site (HTTP over the public domain, plus SSH to the VPS for
out-of-band verification), and is required to leave the site in exactly
the state it found it in -- see revert.py's Cleanup/Probe machinery,
which makes that a structural guarantee rather than a convention any one
probe author has to remember.
"""
