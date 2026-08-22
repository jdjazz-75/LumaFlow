# RAW test fixtures (phase K: 052-055)

This directory holds RAW file fixtures used by the phase-K (RAW support) test suites.

No real decodable RAW file (`sample.cr2`, `sample.nef`, `sample.arw`, ...) is committed here by
default — a genuine decodable RAW file typically weighs several MB to tens of MB and raises a
licensing/redistribution question this project can't settle unilaterally. Tests that need a real
decodable fixture look for
`sample.*` in this directory and skip (not fail) when none is present.

Fixtures that don't require real RAW structure (e.g. `corrupted.cr2`, arbitrary bytes with a valid
RAW extension) are committed directly, since they carry no licensing concern.

To exercise the success-path tests locally, drop a redistributable decodable RAW file here named
`sample.cr2` (or `.nef`/`.arw`).
