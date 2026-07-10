# Citation Verification Dossier — Rivera v. Harmon MSJ

Research pass (web-verified against Justia, CourtListener, Leagle, SCOCAL, leginfo.legislature.ca.gov). Feeds CitationVerifier prompt design + eval gold labels. Caveat: "does not exist" findings based on free legal databases; definitive non-existence would need Westlaw/Lexis.

## Verdict table

| # | Citation | Exists? | Supports proposition? | Quote verdict | Confidence |
|---|---|---|---|---|---|
| 1 | Privette v. Superior Court, 5 Cal.4th 689 (1993) | **YES** — citation correct | Partially — general presumption yes, but brief converts presumption into absolute rule | **"A hirer is never liable…" (Id. at 702) FABRICATED** — sentence not in opinion; "never" strips Privette's qualifier ("who did not cause the injuries") | HIGH |
| 2 | Whitmore v. Delgado Scaffolding Co., 334 F. Supp. 2d 1189 (C.D. Cal. 2004) | **NO — fabricated** | N/A | Parenthetical invented | HIGH |
| 3 | Kellerman v. Pacific Coast Construction, 887 F.2d 1204 (9th Cir. 1991) | **NO — fabricated** (also internally inconsistent: 887 F.2d is 1989-era, not 1991) | No — and the legal rule is independently wrong: OSHA compliance is admissible evidence of due care, never a presumption (29 U.S.C. §653(b)(4) savings clause) | Quote FABRICATED; states a rule US courts don't recognize | HIGH |
| 4 | SeaBright Ins. Co. v. US Airways, 52 Cal.4th 590 (2011) | **YES** — citation correct | **NO — mischaracterized.** Actual holding: hirer implicitly delegates Cal-OSHA workplace-safety duties to contractor (delegation-of-duty holding). Brief recasts it as evidentiary rule ("compliance highly probative of due care") — doctrinally distinct | Paraphrase, materially inaccurate | HIGH |
| 5 | Cal. Code Civ. Proc. §335.1 | **YES** — correctly stated (2-year PI SOL) | YES. But §D self-defeating: brief's own math (1 yr 362 days) shows filing timely; true date (Mar 12) gives 728 days vs 730 limit — timely either way | No quote | HIGH |
| 6a | Torres v. Granite Falls Dev. Corp., 198 Cal.App.4th 223 (2011) | NO — fabricated | — | — | MED-HIGH |
| 6b | Blackwell v. Sunrise Contractors, 45 Cal.App.4th 1012 (1996) | NO — fabricated | — | — | MED-HIGH |
| 6c | Dixon v. Lone Star Structural, 387 S.W.3d 154 (Tex. App. 2012) | NO — fabricated; **also Texas authority = zero precedential weight in CA** | — | — | MED-HIGH |
| 6d | Okafor v. Brightline Builders, 291 So.3d 614 (Fla. Dist. Ct. App. 2019) | NO — fabricated; Florida authority, same jurisdiction defect | — | — | MED-HIGH |
| 6e | Nguyen v. Allied Pacific Construction, 112 Cal.App.4th 845 (2003) | NO — fabricated (vol. 112 Cal.App.4th cases start at pp. 285/1031/1593; position 845 doesn't resolve to this name) | — | — | MED-HIGH |
| 6f | Reeves v. Summit Engineering Group, 78 Cal.App.4th 531 (2000) | NO — fabricated | — | — | MED-HIGH |

**Score: 10 of 12 authorities fabricated or defective.** Real + correctly used: only CCP §335.1. Real but misused: Privette (doctored quote), SeaBright (mischaracterized holding).

## Privette exception landscape (all real, confirmed)

- **Privette (1993) 5 Cal.4th 689** — worker-comp-covered contractor employee has no peculiar-risk tort claim against hirer who "did not cause the injuries". Presumption, NOT absolute bar.
- **Hooker v. Dept. of Transportation (2002) 27 Cal.4th 198** — retained-control exception. Three conjunctive elements (per Sandoval): (1) retained control over relevant aspect of work, (2) actual exercise of that control, (3) affirmative contribution to injury (not merely derivative of contractor's negligence). Passive authority + failure to intervene → hirer wins; stepping in and directing → hirer loses.
- **McKown v. Wal-Mart (2002) 27 Cal.4th 219** — furnishing unsafe equipment = species of Hooker affirmative contribution.
- **Kinsman v. Unocal (2005) 37 Cal.4th 659** — concealed pre-existing hazard known to landowner-hirer, unknown/undiscoverable by contractor, no warning given.
- **Sandoval v. Qualcomm (2021) 12 Cal.5th 256** — controlling synthesis of Hooker test.

### Application to these facts
Foreman Donner (GC's employee) personally directed crew onto the defective east-side section, dismissed a reported safety concern ("We don't have time to re-do the base… Just get up there and get it done"), and ordered work to continue = actual exercise of retained control + affirmative contribution. **Triable issue of fact under Hooker/Sandoval → summary judgment likely defeated.** Schedule pressure alone would be insufficient; the safety-concern override is the load-bearing fact. MSJ never mentions Hooker/Kinsman/McKown/Sandoval — a court would notice the omission of the principal post-Privette authorities.

## Key sources
- Privette: law.justia.com/cases/california/supreme-court/4th/5/689.html
- SeaBright: law.justia.com/cases/california/supreme-court/2011/s182508/
- Hooker: law.justia.com/cases/california/supreme-court/4th/27/198.html
- Sandoval: law.justia.com/cases/california/supreme-court/2021/s252796.html
- CCP §335.1: leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=335.1&lawCode=CCP
- OSHA savings clause: law.cornell.edu/uscode/text/29/653
