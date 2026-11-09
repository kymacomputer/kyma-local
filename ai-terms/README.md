# AI-terms files

Read seven AI-use fields with their sources, detailed decisions and unresolved questions.
Use this file in your own review tool or adapt a copy for another vendor.

The Intercom example preserves seven Index fields, 21 decision rows and 67 source-span records.
Its statements come from an independent public-source review.
Intercom did not author or adopt the file.
The example does not clear a customer's contract or actual feature.

## Read the example

Use Python 3.10 or later from the repository root:

```sh
python3 ai-terms/check.py ai-terms/examples/intercom.ai-terms.json --out /tmp/intercom-terms
```

The output has the complete JSON, source evidence, two CSV tables and `CHECK.json`.
The reader makes no model call, network request or remote write.
It does not create or enable feature flags.

Use `--expected-sha256` to compare a file with a separately trusted reviewed digest.
The example's digest appears in `examples/REVIEWED-ANCHOR.json`.
An absent digest permits an edited file after structural checks.
That edit still requires substantive review.

Use `--source-root` to verify original captured HTML files and their exact byte spans.
The source root must contain the paths in the evidence file.
The public example includes independent interpretations and exact source metadata.
It does not redistribute complete vendor websites or the quoted source paragraphs.
Without original captures, `full_source_bytes_verified` stays false.
A valid evidence-file digest cannot prove the underlying whole document.

## Adapt a copy

Preserve the seven field names in `ai-terms.schema.json`.
Use the actual company, domain, source dates, statements and unresolved questions.
Replace the decision rows and source evidence with the new case.
The format permits a different row count and different source identifiers.
It does not require the Intercom example's 21-row shape or frozen digest.

Every field and decision relation needs source-span identifiers.
Every uncertainty reference must resolve to the file's uncertainty queue.
The evidence file retains each source URL, capture clock, byte hash and excerpt offsets.
Its own byte hash binds it to the terms file.

The checker verifies these references and the evidence-file digest.
It cannot determine whether a statement follows from its cited clause.
Vendor authorship and adoption remain declarations without independent verification.
Customer-specific clearance stays outside this format's scope.

## Sources and clocks

The example retains the November 4 captures and the November 8 and November 9 proposition comparisons.
A later proposition match does not replace the original capture clock.
It does not prove unchanged whole documents, private amendments, tenant applicability or actual notice.
The detailed source relations remain beside the seven summary fields.

The JSON format and new code use MIT under the repository license.
Vendor source material retains its original rights.
The format creates no publisher endorsement or license over a vendor's website.

## Check the reader

```sh
python3 -m unittest discover -s ai-terms -p 'test_*.py'
```

The controls cover a second vendor, edited files, original source bytes, missing references and changed evidence.
They also cover false declarations, duplicate identifiers, unsafe paths and an existing output folder.
These checks prove the stated local behavior, rather than outside adoption or legal correctness.
