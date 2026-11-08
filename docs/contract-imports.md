# Contract exports

Import your existing export and downloaded originals into one local contract folder.
The importer preserves the export bytes, metadata, links and original attachment bytes.
It does not contact the contract system or fetch attachment URLs.

## Ironclad API response

Use a saved response from Ironclad's [List All Records endpoint](https://developer.ironcladapp.com/reference/list-all-records).
The documented response contains `page`, `pageSize`, `count` and `list`.
Each record identifies attachments by their exact keys.
An attachment includes its filename and download URL, with an optional SHA-256 digest.

Acquire the response and attachments under your existing account permissions.
Keep your API token in your own credential store.
This offline route requires no token.

Create a mapping file beside your export:

```json
{
  "schema": "kyma-contract-import-map/v1",
  "records": {
    "YOUR-EXACT-RECORD-ID": {
      "customer_id": "customer-a",
      "attachments": {
        "signedCopy": "customer-a/signed-msa.pdf",
        "dataProcessingAgreement": "customer-a/dpa.pdf"
      }
    }
  }
}
```

Use the actual attachment keys from your response.
Each path is relative to your downloaded originals folder.
Map every exported record to its intended customer folder.
Several records can belong to the same customer.
Customer IDs that differ only by letter case require distinct names before import.
An omitted attachment path remains an explicit missing original.

```sh
kyma-local import --format ironclad-json --export ironclad-records.json --mapping import-map.json --files-root downloaded-originals --out imports/ironclad-first
```

The command returns the exact `contracts` path for the next step.
It rejects inconsistent hashes and ambiguous identities before the first output write.
Use a new output folder for each import.
An existing output remains intact.

This version imports one response page.
The report retains the page, query count and acquired record count.
Unacquired pages remain visible to the agent.
A fully acquired query can still omit agreements through permissions or filters.

## Review-table CSV

Use these exact headers for a user-defined review table:

```csv
document_id,customer_id,file,Reviewer note
msa-1,customer-a,customer-a/signed-msa.pdf,Review the original terms
dpa-1,customer-a,,Original DPA still required
```

Keep every additional column that matters to your review.
The importer preserves all cells as literal strings.
Quoted commas, Unicode and multiline cells remain intact.
A blank `file` cell records a missing original.

```sh
kyma-local import --format review-table-csv --export review.csv --files-root downloaded-originals --out imports/review-first
```

This CSV schema belongs to Kyma Local.
It does not claim compatibility with a proprietary Harvey or Legora export.
LinkSquares documents an [XLSX report with agreement links](https://help.linksquares.com/hc/en-us/articles/8762862403095-Reporting-in-Analyze).
This version does not parse that workbook or treat its links as downloaded contracts.

## Use the imported originals

```sh
kyma-local-agent prepare --contracts imports/ironclad-first/contracts --feature my-feature.json --out runs/imported-feature
```

The normal source reader exposes each complete original and its import provenance.
The preparation also returns record relationships, missing files and query coverage.
Your agent resolves legal precedence from the actual source documents.
Record order, parent IDs and relationship links supply context without an automatic hierarchy.

The imported folder contains a private `.import` folder with the exact export and mapping.
Its `_import.json` records the copied originals and incomplete-set state.
Keep these files with the contracts.
Preparation rejects a changed original, a corrupt import or an interrupted import.
The reader reconstructs missing-file and provenance indexes from the preserved export and acquired originals.
For a changed contract, import the new original into a new folder.
Then use the existing revision command with that folder.

A metadata-only change also reaches the revision reader.
For example, a changed query count can reveal an omitted record without a changed contract file.
An identical reimport creates no revision solely because its local capture clock differs.

The MCP server exposes `import_contract_export` with the same arguments and result.
Then use `prepare_contract_job`, `read_contract_source`, `submit_contract_assessment` and `read_contract_result` as usual.

## Verified scope

Run the focused checks from the installed kit:

```sh
python3 scripts/bootstrap.py --mcp
.venv/bin/python scripts/check_importers.py
```

The test uses synthetic Ironclad metadata and CSV rows with four original public contracts.
It checks the actual CLI, stdio MCP, source reader, existing decision compiler, OpenFeature SDK and SQLite receiver.
It retains the original model interpretation through an exact document-ID remap.
It does not establish an outside customer's export, new model interpretation, live API access or customer adoption.

## Compare your existing result

Use the same complete documents and feature facts for both tools.
Keep the original contract-system answer beside the Kyma result.
Compare the source citations, amendments, proposed conditions and next action.
Preserve an equally useful native answer as a successful alternative.

An exported row is metadata until its original documents reach the local source reader.
The query count and missing-file report remain part of that reader's context.
Neither a full query nor an import creates a complete-set attestation.
