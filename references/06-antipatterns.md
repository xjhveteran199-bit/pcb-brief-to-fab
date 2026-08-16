# Antipatterns

Each item below is a real failure from a real project, written as the symptom you
will actually see, the root cause, and the rule that prevents it.

## 1. The suspiciously green gate

**Symptom.** Every check passes. The board still has a defect that any engineer
would catch in thirty seconds.

**Cases.** 115 tests green while a P0 data-integrity defect sat in the code. A
sandbox connectivity model reported PASS while the real KiCad export was missing
15 nodes. A router reported 218 connections routed while the real DRC found 883
violations.

**Root cause.** The checker and the artifact share an assumption. Your model of the
tool is not the tool.

**Rule.** When a result is surprisingly clean, verify it with a *different*
mechanism — the real tool, an independent parser, a rendered image, a second pair
of eyes. Ask what this check would fail to catch, and then go check that thing.

## 2. The hardcoded condition disguised as a check

**Symptom.** A script asserts a property and returns True.

**Case.** A script contained `if "Codex" in link:` and concluded from it that a
path no longer existed. Measurement showed the path was alive and healthy, and a
subsequent audit found 10 unmerged branches and 3 worktrees holding uncommitted
work — including 468 lines of application code that a "safe cleanup" would have
deleted.

**Root cause.** The answer came from a literal in the source, not from the system.

**Rule.** An existence check queries the system. A capability check runs the tool.
If you catch yourself writing the expected answer into the condition, stop.

## 3. Regex on a structured file

**Symptom.** A parser processes some records and silently skips the rest.

**Case.** `re.search(r'\(property\s+"Reference".*?\)\)', text, re.S)` returns
`None` on an indented, newline-formatted `.kicad_sch` because the literal `))`
never appears. 92 of 180 footprints were processed; the other 88 were skipped
without any error. It surfaced only when DRC produced 161 silkscreen warnings.

**Rule.** Parse S-expressions with a paren-matching reader, XML with an XML parser,
CSV with a CSV reader. And make the "not found" branch *loud* — count what you
processed and compare it to what you expected.

## 4. Reasoning about rendering instead of looking at it

**Symptom.** A layout metric says the drawing is fine. The engineer says it is
unreadable.

**Cases.** Extracting text from a KiCad-generated PDF to count overlaps produced
1005 phantom overlaps, because the PDF carries both a searchable text layer and
vector-stroked glyphs and CJK text is UTF-16. Separately, an approximate in-sandbox
renderer with estimated glyph widths passed a page a human could not read.

**Rule.** Compute geometry facts from the source file. Judge appearance from a real
rendered image, viewed. Never from extracted PDF text.

## 5. Non-idempotent transformations run twice

**Symptom.** The second run of a "fix" silently loses something the first run
preserved.

**Case.** A retrofit script reconstructed power-flag connections from the labels
that existed *before* the retrofit. Those labels no longer exist after run 1, so
run 2 dropped the connections and left whole rails with no driving source.

**Rule.** Label non-idempotent scripts in their own docstring and in the tool
index. Restore the pre-transform state before re-running. Prefer generators that
delete their output and regenerate it from scratch.

## 6. Percentage as a release claim

**Symptom.** "58 % routed" drifts into a status report and then into a release
note.

**Rule.** A percentage is an experiment result. Only three numbers gate a release:
blocking DRC violations, unconnected items, schematic parity differences — all
zero. Anything else is `ENGINEERING_HANDOFF`.

## 7. Two documents, two truths

**Symptom.** Board size, layer count, revision, or DNP policy differs between the
manifest, the handoff document, the order form, and the `.gbrjob`.

**Cases.** A manifest field named for the product outline actually held the
placement area, and two readers took it as the board size. A via-pad rule was
documented as 0.30 mm while the project's DRC enforced 0.50 mm, and the handoff
quoted both on the same page. A `.gbrjob` recorded 31.1 × 88.1 mm against a
documented 38 × 90 mm.

**Rule.** One controlling number, in the manifest, with a `why`. Everything else
quotes it or derives it. A checker that finds a disagreement blocks; it does not
pick a winner.

## 8. Stale evidence next to changed files

**Symptom.** An old "ERC: 0 errors" line sits beside a schematic edited last week.

**Rule.** Every report names the file hash it describes. When the hash changes, the
report is void — strike it through or delete it, never leave it standing. Re-run
before quoting.

## 9. Laundering a failure into a release

**Symptom.** A blocked output directory gets renamed to `final`, or a `--force`
flag overwrites the previous attempt.

**Rule.** New directory per attempt. Never delete or rename evidence. A blocked run
is a legitimate, valuable artifact — it is the proof that the gate works.

## 10. Self-review presented as independent review

**Symptom.** "Reviewed and approved" where the reviewer was the same agent, or the
same model in a fresh context.

**Rule.** A fresh-context adversarial review is better than nothing and is worth
running for safety logic, data integrity, and fabrication output. State plainly
that it is weaker than review by a genuinely separate implementer — same model,
correlated blind spots. For `HIGH` risk, it does not substitute for a named human.

## 11. Generating artifacts while blocked

**Symptom.** The work that matters needs bench measurements or a human decision, so
the agent produces more documents instead.

**Rule.** When every remaining path is blocked on something only the operator can
provide, say exactly what is needed, from whom, and stop. Additional provisional
artifacts add review burden and move no gate.

## 12. Cosmetic work without feedback

**Symptom.** Endless re-tuning of layout aesthetics, autorouter parameters, or
schematic appearance based on guesses about what the reviewer wants.

**Rule.** Beautification has no natural endpoint. Get the reviewer's specific
objection first, then change exactly that. If they say "I can't read it", the next
question is "which part", not another revision.

## 13. Shell string composition around a real tool

**Symptom.** Quoting and redirection silently swallow output; a path with a space
splits into two arguments; an error is lost because only stdout was captured.

**Rule.** Build argument arrays, not command strings. Capture stdout, stderr and
the return code separately. Put complex logic in a script file and invoke the
script. Never let a project-local binary shadow a system tool.
