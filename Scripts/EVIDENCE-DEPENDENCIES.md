# Evidence dependency inventories

[`evidence-dependencies.json`](evidence-dependencies.json) is the maintained source inventory for the global solar, local solar, observer event, planetary event, transit, Pluto observer, and Galilean residual artifacts. It lists exact repository paths rather than discovering every Swift file below `Engine`.

Each shared group declares its required owners, and each owner declares its groups. The loader requires those declarations to agree, requires the complete owner set, rejects duplicate or malformed paths, and requires every expanded path to be a file. A missing or renamed dependency therefore stops recording and checking instead of silently reducing coverage.

When a result starts using another file, add its exact path to an existing group or add a new group, then add every affected owner to both the group and owner declarations. Keep a dependency when its influence is uncertain. Do not add unrelated files to make a check pass.

Run `python3 Scripts/test_evidence_dependencies.py` after editing the inventory. Its controls cover direct and transitive edits, unrelated Engine additions, inventory additions, physical deletion or rename, malformed and duplicate entries, and missing required ownership coverage.

An ownership-only migration can rebind archived measurements only when `verify_retained_inputs` proves that every retained result dependency still has its preceding digest and `verify_rebound_document` proves that every non-binding evidence field is identical. The shared inventory files, the executing recorder, and Python replay tests are replay machinery; changes to runtime sources, generated inputs, Swift capture tests, fixtures, or references require a fresh capture.

Use the recorder command for the affected artifact and then its `--check` command. Planetary event evidence uses `--rebind` for a guarded ownership-only migration, Pluto observer evidence uses `--rebind-native`, and Galilean residual evidence uses `--capture` when its Swift measurement owner or result inputs change. Never edit a stored digest by hand.
