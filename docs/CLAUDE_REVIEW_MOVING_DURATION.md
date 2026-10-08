# Preprocessor Claude — independent moving-duration code review

Read HANDOFF.md, current parent CONTEXT.md and docs/MOVING_DURATION.md. Review the actual moving-duration fix within the approved v3 architecture; this is the last frozen v1 data-contract fix, not a feature expansion.

Run `.venv/bin/python -m unittest discover -s tests -v` (123 expected). Rebuild independently with data/i284770_fit_files(1).zip, data/i284770_activities(2).csv, data/device_mapping_current.csv and the preserved user resolutions. Use a separate ignored output directory; do not replace the reviewed routine upload or run bridge imports yet.

Inspect:
- Existing estimated_stationary_duration_s is analyzed stationary time inside pauses/gaps, not timer-running-only stationary time. It must never be subtracted blindly from timer/moving values.
- FIT/Intervals moving metrics are validated source-owned metadata; timer/elapsed/recorded_active_duration_s are not substitutions. Documented CSV enrichment and moderate source confidence are appropriate.
- Record fallback excludes timer pause overlap once, stationary active bins, terminal/duplicate stops; full-coverage checks, missing timer handling, speed bounds and missing signals stay conservative.
- Accepted moving-distance repair selects complete continuous-source moving time. Physical motion while Garmin was left paused is distinguished from a stationary stop; partial Garmin active pace remains unchanged.
- Preferred durations beyond existing canonical elapsed bounds are not clamped. Sep8/Sep29 use a measured alternative tied to the exact canonical clock. Challenge any source/window mismatch.
- Sep7 alone remains unknown, with unresolved-outing-motion provenance despite source moving metrics. Check whether this conservatism matches canonical full-coverage semantics; escalate any semantic disagreement to PE before changing it.
- Full candidate has 77 moving values / changed revisions, unchanged 78 IDs, no retirement, same 242.375228 foot mi and one existing Sep7 review. Oct5=8146 s, Oct6=2212 s. No unrelated canonical column or source row changed.
- Every populated duration satisfies 0 <= moving <= canonical elapsed. Revisions change on moving-value changes and remain deterministic on rerun. Unknown time does not become zero.
- ZIP/privacy exclusions and original FIT/CSV/resolutions/routine ZIP preservation.

Fix defects if needed, rerun tests and update HANDOFF.md with approval/findings. Codex reviews your fixes. Do not push, deploy, modify Sheets, publish this as reviewed in CONTEXT, or hand the candidate archive to the bridge before approval. After review Codex regenerates the routine ZIP and supplies the exact reviewed coordination entry to Bridge Codex.
