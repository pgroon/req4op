# REQ4OP

A tool for generating Requirements Engineering reports from OpenProject (OP). Currently OP lacks any native tools for requirements engineering, both in the community as well as the enterprise edition.

The goal is to have a simple way to generate a trace matrix and/or a (complete, versioned) requirements overview doc with as little effort as possible. 

v0.1 renders the full linked wiki page inline. This assumes page-to-requirement alignment, which does not hold as a wiki matures (pages outgrow, share, and split across requirements).
Eventually links will be section-anchored rendering will be duplication-aware and either use citations or in-document links.
