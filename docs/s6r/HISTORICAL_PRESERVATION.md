# Historical Freeze and Archive Recheck

**Overall:** `PASS_WITH_DOCUMENTED_SOURCE_EVOLUTION`  
**Evidence:** [`HISTORICAL_PRESERVATION.json`](HISTORICAL_PRESERVATION.json)

- All nine retained G0, G1, G2, G3, G4, and S5 audit ZIPs pass `zipfile.testzip()` and match the archive hashes recorded in the historical ledgers. The G4 archive hash is `866d305aa87920c2068fb964ba4c3c7ff401964391ddf452bb022ed76ce9914d`; the S5 archive hash is `18d946e3c3d9cecadab558a05c262c8b1c286fa062ae11050037b6ed3df13ec5`.
- G4 freeze/base manifests (179 and 6 files), S5 freeze (10 files), S6 freeze (21 files), S6 Amendments 01–03 (12, 49, and 22 entries), and 28 S6 pre-holdout code-freeze entries verify against their recorded hashes and sizes.
- The G3 baseline explicitly describes itself as `pre_change_baseline`. Two source file hashes therefore differ from the later checkout. Their current bytes match the corresponding source members in the later G4 and S5 audit ZIPs: `src/optisys/gates/g2.py` matches G4 and `src/optisys/cli.py` matches S5. Those differences are documented code evolution; the G3 archive and run artifacts remain unchanged.
- The standalone S6 pre-registration Markdown file is absent. The frozen acceptance criteria and pre-result holdout freeze contain the decision rule used for the S6-C recheck; the separate missing file is recorded in the input map.

The intake snapshot hashes the complete S6 run directory before any S6-R work. A final comparison is recorded after validation to prove the source tree stayed unchanged.
