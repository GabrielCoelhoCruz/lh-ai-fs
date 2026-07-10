# Ground-Truth Flaw Audit — Rivera v. Harmon MSJ

Adversarial audit of `backend/documents/motion_for_summary_judgment.txt` against the three source documents. This is the provenance for `backend/evals/gold.json`. Line numbers refer to the source .txt files.

True incident date per all three source docs (+ surgery date): **March 12, 2021**. MSJ asserts March 14, 2021.

Day math (computed): MSJ date 03/14/2021 → filing 03/10/2023 = 726 days; true date 03/12/2021 → filing = 728 days; limit = 730 days. **Timely under both dates.** Surgery on 03/13/2021 makes 03/14 physically impossible as injury date.

## (A) Flaws the pipeline must catch

| ID | Category | MSJ location | Claim | Evidence | Why flawed | Sev | Conf |
|---|---|---|---|---|---|---|---|
| F1 | cross-doc-contradiction | §I ¶1 (L19), Fact #3 (L27), §III.D (L55) — 3× | "a workplace incident on March 14, 2021" | Police L6/L41, Medical L9/L19, Witness L17 all say **March 12**; Medical L54: surgery 03/13/2021 — cannot precede claimed injury date | Date fabricated; unanimous contradiction; surgery clincher | High | High |
| F2 | cross-doc-contradiction | Fact #4 (L29) | "Rivera was not wearing required personal protective equipment… including fall-arrest equipment" | Police L51-52: Ellison confirmed hard hat + harness; lanyard attached, anchor point was part of collapsed section. Witness L35, L40-41 same | Directly false; MSJ inverts causation — harness failed because anchor collapsed | High | High |
| F3 | omission/misleading-framing | §III.A ¶2 (L41), premise ¶1 (L39) | "Apex… not Harmon — was the employer responsible for scaffolding operations… safety" | Police L55-56: Donner (Harmon foreman) directed crew to east-side section, schedule pressure, "That's Apex's responsibility. I told them where we needed them working." Witness L25-26, L33 ("We don't have time to re-do the base… Just get up there and get it done"), L47-48 | Omits retained control — Hooker/Sandoval exception facts entirely absent | High | High |
| F4 | omission/misleading-framing | §III.B ¶2 (L47), Fact #5 (L31) | "unblemished OSHA inspection record… effectively insulating it from tort liability" | Police L67: Cal/OSHA investigation pending; Police L47-48: rust, detached braces, plywood base; Witness L29-33: defects reported to Ellison AND Donner pre-incident; Witness L49: post-incident full rebuild w/ concrete footings | Omits pending investigation + documented reported defects. (Rebuild folded here; see C4) | High | High |
| F5 | doctored-quote | §III.A ¶1 (L39) | "'A hirer is never liable…' Id. at 702" | Privette real (5 Cal.4th 689) but sentence not in opinion; "never" converts rebuttable presumption into absolute bar; contradicted by Hooker/Kinsman/McKown/Sandoval | Fabricated quote w/ pin cite. Citation itself real — never label "fabricated" | High | High |
| F6 | mischaracterized-holding | §III.B ¶2 (L47) | SeaBright cited for "compliance… highly probative of due care" | SeaBright real; actual holding = hirer delegates Cal-OSHA safety duties to contractor (delegation, not evidentiary weight) | Real case, wrong proposition | High | High |
| F7 | fabricated-citation + fabricated-quote | §III.B ¶1 (L45) | Kellerman v. Pacific Coast Construction, 887 F.2d 1204 (9th Cir. 1991) + OSHA-presumption quote | **Web-verified: does not exist** (Justia F.2d index). Legal rule invented — 29 U.S.C. §653(b)(4); OSHA compliance is evidence, never presumption. Soft tell: 887 F.2d ≈ 1989, not 1991 | Fabricated case + fabricated rule | High | High (reconciled) |
| F8 | fabricated-citation | §III.A ¶2 (L41) | Whitmore v. Delgado Scaffolding Co., 334 F. Supp. 2d 1189 (C.D. Cal. 2004) | **Web-verified: does not exist.** Parenthetical fuses Privette w/ assumption-of-risk contrary to Li v. Yellow Cab (1975) | Fabricated | Med-High | High (reconciled) |
| F9 | fabricated-citation | Footnote 1 (L71) | Six-case string cite (Torres, Blackwell, Dixon, Okafor, Nguyen, Reeves) | **Web-verified: none exist.** Dixon (Tex.) + Okafor (Fla.) additionally non-binding in CA. Nguyen's reporter slot occupied by other cases | Bulk fabricated cite + jurisdiction padding | Med-High | High (reconciled) |
| F10 | unsupported-assertion | §III.C ¶1 (L51) | "over eight years of experience" | No doc states tenure. Occupation confirmed only (Police L25, Witness L8) | No evidentiary basis; stated as fact. Scoring: accept `unsupported` OR `could_not_verify` | Med | High |
| F11 | unsupported-assertion | §III.C (L49-51) | Assumption-of-risk argument | Zero citations (only argument section without authority). Witness L35, L51: Rivera followed protocols; hazard was reported + dismissed, not inherent trade risk. Doctrine as framed (complete bar) misstates CA law post-Li v. Yellow Cab (1975) | Uncited argument, factually undercut, misstated doctrine | Med | High |
| F12 | misleading-framing | §III.D heading + body (L53-55) | Heading "Time-Barred" | Body concedes "falls nominally within this window"; 726/728 days < 730 both ways; "reserves the right to challenge accrual" states no basis | Self-defeating heading | Med | High |

## (A2) Unverifiable — correct pipeline output = `could_not_verify` (NOT flaw findings)

| ID | MSJ location | Claim | Why |
|---|---|---|---|
| F13 | Fact #5 (L31) | "passed all OSHA inspections… most recent being February 26, 2021" | No inspection records in corpus; date unconfirmable. Distinct from F4 (framing/omission is the flaw, not the inspection claim itself) |
| F14 | Fact #5 (L31) | "Harmon maintained an active IIPP" | Not mentioned in any source doc |

## (B) Precision traps — TRUE/consistent claims, must NOT be flagged

| ID | Claim | Why true |
|---|---|---|
| P1 | CCP §335.1 = 2-year PI SOL (§III.D) | Correct statement of law |
| P2 | Filing "falls nominally within this window" | 726/728 days < 730 — timely both ways |
| P3 | Privette citation (5 Cal.4th 689 (1993)) | Real, correct cite. Flag only doctored quote (F5) |
| P4 | SeaBright citation (52 Cal.4th 590 (2011)) | Real, correct cite. Flag only mischaracterized holding (F6) |
| P5 | ~14 ft fall height | Police L43, Medical L17, Witness L39 all agree |
| P6 | Rivera employed by Apex, subcontractor to Harmon | Confirmed across docs |
| P7 | Harmon = GC at 2200 W Olympic Blvd | Confirmed (Police L34, Witness L21) |
| P8 | Location 2200 W Olympic Blvd, LA | Confirmed |
| P9 | Scaffolding section collapsed beneath Rivera | Confirmed all docs |
| P10 | "injuries were immediately apparent" | Medical L19: "immediate onset of severe pain" — factually true |
| P11 | "journeyman scaffolder" occupation | Police L25 confirms; only "eight years" (F10) unsupported |
| P12 | Age distractor: Medical L17 says "36-year-old male", DOB 06/18/1985 → 35 at incident | Internal inconsistency of SOURCE doc; MSJ makes no age claim → must not be reported as MSJ flaw |

## (C) Judgment calls — resolved

1. **"one year and 362 days" arithmetic**: ambiguous day-counting convention (exclusive = 361, inclusive = 362). NOT scored as flaw; substance covered by P2/F12.
2. **Age discrepancy** → gold negative P12 (source-doc distractor).
3. **F10 scoring** → accept-either: `unsupported-assertion` OR `could_not_verify` both count as correct.
4. **Post-incident rebuild** → folded into F4 evidence (subsequent remedial measures inadmissible under Cal. Evid. Code §1151 — defensible for MSJ to omit as standalone).
5. **Case number "BC-2023-04851" anachronism** (BC prefix legacy LASC numbering) → excluded from gold set, low confidence it's planted.
6. **F7/F8/F9 fabrication labels** → reconciled with web-verification dossier (docs/research/caselaw-dossier.md): all confirmed non-existent. Pipeline scoring: `likely_fabricated` OR `could_not_verify` both acceptable for these (pipeline has no legal DB); emitting a confident *holding* for a fabricated case = hallucination penalty.
