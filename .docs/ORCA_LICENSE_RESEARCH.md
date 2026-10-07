# ORCA June 2025 EULA: CoChem and GitHub-hosted Actions assessment

Assessment date: 7 October 2026. Target executable: ORCA 6.1.1.

## Conclusion

**The supplied EULA does not clearly authorize the proposed GitHub-hosted installation, and it does not expressly prohibit all cloud use.** It permits installation and necessary copies, while restricting third-party availability and transfers outside its scope. Whether an ephemeral GitHub runner is the licensee's permitted installation, or an impermissible transfer/making-available to a third party, is not expressly resolved. A private repository and temporary installation address access controls; they do not settle that contractual interpretation.

A workable route for **CoChem development and integration tests** is an eligible academic research-group deployment with an established license basis covering the hosted installation, authorized users, provider processing, and result handling. Obtain written interpretation or appropriate additional terms from the licensor where those points remain unclear. This is a recommendation to resolve identified ambiguity, not a claim that the EULA expressly requires advance written consent for every cloud installation.

For **routine production research calculations**, GitHub's independently applicable development/testing restriction also needs resolution. For a **public, multi-institutional or commercial CoChem calculation service**, this EULA does not supply blanket permission for all users, binaries, data or software use. Additional licensing and platform terms would be needed for activities outside its scope.

## Primary document and applicability

The user supplied `EULA_ORCA_2025.pdf`, a five-page document whose final page states **"Version: June 2025"**. All five pages were read; the data provisions on page 3 were also checked against a rendered page. Its SHA-256 is:

`0847140c6157200c497f4142a7959e22984861bbd8f785dd2f3e2238e392a4cd`

The original attachment is retained at `/tmp/codex-remote-attachments/01a113a5-0dfb-7736-b0e1-8c3f0ae850db/2606a66f-603e-4a16-8bcc-b0e1585ec1e3/1-EULA_ORCA_2025.pdf`; extracted text is in `/workspace/.cochem-setup/orca-license-research/EULA_ORCA_2025.txt`. This report records short relevant quotations and analysis rather than redistributing the attachment in Git.

Section 1(c), page 1, defines SOFTWARE as ORCA **version 4.0 or later**, and the introduction applies the conditions to updates and upgrades. Thus 6.1.1 falls within the version definition. The document's text is now available for review; the separate questions of whether this is the agreement applicable to the user's distribution, whether an institutional agreement modifies it, and whether later notified changes apply remain factual matters. Section 11, page 5, addresses notified changes to the conditions. This review does not certify that June 2025 is the latest agreement offered worldwide.

The named contracting parties are the user and **Max-Planck-Institut für Kohlenforschung, acting through Studiengesellschaft Kohle mbH (MPI/SGK)**, page 1. FACCTs is not named in this PDF. A licensing representative must be able to give an authoritative interpretation or applicable separate agreement; commercial permission cannot be inferred from this academic EULA.

## Installation, purpose and users

| Provision | What the supplied text says | Consequence for CoChem |
| --- | --- | --- |
| §1(a–b), p. 1; §2, p. 2 | Use is exclusively in defined ACADEMIA for ACADEMIC PURPOSES, or defined PRIVATE USE. Academic purpose excludes specified commercial R&D, for-profit sponsorship/collaboration and provision of research/results to for-profit organizations. | Confirm the licensee and actual purpose. Nonprofit status alone does not necessarily qualify an organization as ACADEMIA. The express journal-publication permission in §3(c) must also be respected when interpreting results sharing. |
| §1(d), p. 1 | PRIVATE USE is a single person's noncommercial, **"not work-related research only"**; it excludes organizational use and persons whose work could benefit. | A private GitHub repository is not the defined PRIVATE USE. An academic work project should rely on the academic-use basis. |
| §2, p. 2 | For research-group use, the licensee guarantees members' compliance and is MPI/SGK's contact. | Group use is expressly contemplated. This clause does not require separate registration for every member, nor authorize an unrestricted public user population. |
| §3 opening grant, p. 2 | Permitted use includes installation/running and duplication **"insofar as such duplication is required to use SOFTWARE."** | Necessary temporary copies can be permissible; network copying is not categorically banned. The use must remain within the agreement. |
| §1(g), p. 2; §3(a), p. 2 | Third party includes any party involved in using SOFTWARE, DATA or DATABASES. Software cannot be transferred or made available to third parties except as expressly provided; public accessibility and sublicensing are restricted. | GitHub, archive-provider, operator and automated-service access need assessment. There is no explicit cloud-provider/processor exception in this text. |
| §3(b), p. 2 | Restricts collaboration with for-profit and nonacademic governmental/nonprofit organizations, including contract calculations; its limitations do not apply if all partners have valid licenses for software or contract calculations. | Buying compute is not expressly defined as research collaboration. Conversely, the licensed-partners exception addresses §3(b), not every restriction elsewhere in the EULA. |
| §3(i), p. 3 | Prohibits network transfer **"if said transfer is not within the scope of this Agreement."** | Determine the scope of the specific hosted transfer; this wording neither grants unrestricted cloud transfer nor bans every network installation. |

No provision names GitHub, Actions or cloud hosting, or expressly requires institution-owned hardware. There is a plausible permitted-use interpretation for a controlled machine acting solely for an eligible licensee, but the broad third-party wording leaves an unresolved issue for managed GitHub infrastructure. The conclusion is conditional, not a categorical cloud ban or an approval.

## Data and software conditions materially affect CoChem

Sections 1(e–f), page 1, define DATA as **all data generated by ORCA** and DATABASE as **any organized or random collection** of that data. ORCA-generated energies, geometries, gradients, Hessians and scientific output logs—and HDF5 collections, exported tables or regression datasets containing them—therefore need to be treated as covered material. Selecting values or changing the file format does not clearly remove these conditions.

| Provision, all on p. 3 | Consequence |
| --- | --- |
| §3(c) | **"Publication of data in a scientific journal is expressly permitted."** Other third-party sharing is limited to ACADEMIC PURPOSES. This exception supports scientific publication; it is not an express blanket permission for every dataset repository, license or supplementary-data arrangement. |
| §3(d) | Database sharing must be noncommercial and follow the EULA. Shared data must include a copyright notice, an explicit EULA notice and the **verbatim §7 warranty disclaimer**. The DATA sublicensing exception does not grant binary sublicensing rights. Determine the appropriate copyright attribution; this clause alone does not identify the owner of every result. |
| §3(e) | **"Any software using DATA"** or software produced partly with that data **"must be used subject to the conditions of this EULA."** This unusually broad provision is directly relevant to CoChem parsers, processing, data-driven development and downstream use. |
| §3(f) | Restricts databases usable for commercial purposes and uploads to databases that do not prohibit commercial purposes. Blanket CC0 or Apache licensing of covered result datasets would offer commercial reuse inconsistent with that wording. The additional phrase about an "open source license" does not clearly reconcile these restrictions with conventional open-source licenses that allow commercial use. |
| §3(g) | SOFTWARE or DATA may be used for ML only for ACADEMIC PURPOSES. Academic ML is not categorically forbidden. Training, fixtures, weights and downstream use need scope-specific assessment. |

**Section 3(e) is a contractual use condition, not proof that the EULA automatically transfers copyright in CoChem or converts every independently authored Apache-2.0 file into an ORCA derivative.** Nevertheless, CoChem's Apache-2.0 declaration does not cancel the obligations of a licensee who accepts this agreement. Separating code and data helps provenance but does not itself resolve §3(e). Obtain a precise interpretation covering ordinary wrappers, parsers, regression testing and downstream CoChem users before promising unrestricted ORCA-enabled use.

Likewise, §3(f) leaves questions about dataset-specific restrictions versus the hosting database's broader policies. Ask specifically about GitHub artifacts, GitHub-hosted datasets, journal supplements and publication repositories. Private access is an exposure control; it does not itself establish authorized provider handling. Independently sourced xTB data and independently authored analytical fixtures must not automatically be assigned ORCA conditions merely because CoChem also supports ORCA.

Section 5, page 4, additionally requires relevant patent notification, addresses assignment of claims against downstream violators and liability where recipients were released from liability, and requires the citation below for scientific publication. Those provisions matter when granting downstream waivers or distributing datasets.

> F. Neese, “Software Update: The ORCA Program System—Version 6.0,” *WIREs Computational Molecular Science* **2025**, 15:e70019. DOI: [10.1002/wcms.70019](https://doi.org/10.1002/wcms.70019).

This bibliography is verified from the supplied EULA, not from retrieval of the journal article. Record the actual executable version 6.1.1 separately and add applicable method citations as §5 requires.

## GitHub's separate agreement

[GitHub's official Actions terms, reviewed pinned source](https://github.com/github/docs/blob/8794b3cd6aa66cc91c0dba5f15b8864b8636d1fb/content/site-policy/github-terms/github-terms-for-additional-products-and-features.md#actions), state:

> "You may only access and use GitHub Actions to develop and test your application(s)."

They also prohibit, for GitHub-hosted runners, activity unrelated to the production, testing, deployment or publication of the repository's software project, and address disproportionate server burden and commercial services offering Actions.

A small ORCA smoke or regression calculation that actually tests CoChem has a clear application-testing purpose. Ordinary research campaigns or a general chemistry-job service cannot be assumed covered simply because CoChem and molecular inputs live in a repository. Obtain an applicable agreement or authoritative GitHub clarification for that production use. ORCA permission cannot waive GitHub's terms, and calling a production job a test does not change its purpose. Different account agreements may matter.

## Assessment of the prepared implementation

The [manual workflow](../.github/workflows/orca_hosted.yml) and [deployment guide](ORCA_GITHUB_ACTIONS.md) already provide useful controls: a private default-branch controller, a protected environment, a reviewed private archive, checksum verification, temporary installation, fixed serial water smoke input, and explicit calculation evidence. These controls are suitable components of an authorized integration-test deployment.

They do **not** establish the licensee's eligibility or resolve §§3(a/e/i). The environment flag records an operator attestation; it is not licensor permission. Receipt of this PDF is not authorization to enable it. Genuine ORCA and hosted execution remain untested.

The implementation also has specific publication gaps relevant to this assessment:

- [ORCA references](../topos/references.py) include an ORCA website reference but do not yet include the mandatory §5 citation above.
- [Local export](../topos/publication.py) correctly avoids a publication-ready claim, but accepts an arbitrary supplied license identifier. It does not enforce ORCA-specific dataset licensing or insert the required notices and full §7 disclaimer.
- The current worker's evidence artifacts need an agreed access/retention and DATA-handling basis before deployment; binary exclusion alone is insufficient.

These are identified gaps, not a claim that current bundles comply with the June 2025 EULA. This task evaluates and updates documentation; it does not grant rights, accept the agreement, change CoChem's license or activate ORCA execution.

## Concrete route to an authorized deployment

1. Identify the eligible licensee, institution/research group, permitted purposes and authorized CoChem users. Confirm which agreement governs the installed ORCA distribution.
2. Obtain authoritative clarification or additional terms covering the private archive, ephemeral GitHub-hosted installation, provider/operator/agent access, required copies, and output storage. Explicitly address §§1(g), 3(a) and 3(i); clarify §3(b) where external partners or sponsors are involved.
3. Resolve §3(e)'s application to the Apache-2.0 CoChem wrapper and downstream use, and agree dataset/fixture/publication/ML terms under §§3(c–g). Implement the resulting notices, rights metadata, citation and export restrictions before public ORCA-data distribution.
4. Use GitHub-hosted Actions for actual development/testing within GitHub's applicable terms. Treat production calculation hosting as a separate platform-permission question.
5. Record the applicable agreement/version and scope with the deployment, then run and inspect the genuine installation and integration evidence.

A focused request to the licensor or authorized licensing representative is:

> Under our [identify licensee/institution] agreement for ORCA 6.1.1, may our specified academic group store a private distribution archive and execute it on ephemeral GitHub-hosted Linux Actions runners solely to develop and test CoChem? Please clarify §§1(g), 3(a), 3(b) and 3(i) for hosting-provider, operator and automated-service access, required copies, and retention. CoChem's independently authored source is Apache-2.0: please clarify §3(e) for its parsers, workflows, regression fixtures and downstream users. Please also specify permissible private artifact storage, journal supplements and public dataset terms under §§3(c–g), including copyright/EULA notices and the §7 disclaimer. If a separate license or addendum is required, please identify the terms that cover this arrangement.

No inquiry was sent. For production compute on GitHub-hosted runners, a separate GitHub platform clarification is also needed.

## Earlier research superseded

The earlier assessment could only identify older ORCA EULA references because official sites were blocked. The supplied June 2025 PDF resolves the missing-text problem for this assessment. It supersedes reliance on the matrix's older quotations and its unverified personal-Codespaces interpretation. The previously saved network draft may still help independently verify the latest offered terms, but network access is no longer a prerequisite to reading the attached agreement. Earlier validation receipts describe evidence available at their own timestamps; reviewing this PDF does not turn those receipts into ORCA execution or license-authorization evidence.
