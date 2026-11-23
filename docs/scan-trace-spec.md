---
title: Scan-Trace Parquet Specification
document_version: "1.1"
schema_version: "1"
reference_validator: rawtrace_qc.traces.validate_trace
---

# Scan-Trace Parquet Specification

## 1. Purpose and scope
Defines a vendor-neutral Parquet standard for raw-file extractors (Bruker Python reader; Thermo `ThermoScanHeaderExtractor`), independent of any tool's internal naming. Any extractor emitting conforming files is a valid producer; any consumer relying only on the guarantees here is valid. The primary consumer is a TIC/base-peak viewer.

The contract does not fix exact numeric bit widths except where §5/§8 state otherwise. It fixes: file naming, column names, logical types, units, required vs. optional columns, row ordering, null semantics, and vendor caveats affecting a value's *meaning*.

*("Scan-trace" and "scan-table" are used synonymously; filenames use the `-trace` tag.)*

## 2. Terminology
| Term | Meaning |
|---|---|
| **Run** | One acquisition: a Thermo `.raw` file or a Bruker `.d` folder. |
| **Spectrum** | One physically distinct mass spectrum at one time point (one precursor isolation event, for MSₙ). |
| **Frame** | A Bruker TIMS acquisition unit. MS1: one frame = one spectrum. PASEF/diaPASEF MSₙ: one frame can bundle several precursor isolation events into one pre-summed record. |
| **Row** | One record in a file. See §7. |
| **MS1 file / MSn file** | Files containing only MS1 rows / MS2-and-higher rows. |

## 3. File pair and naming
```
<original-name>.ms1-trace.parquet
<original-name>.msn-trace.parquet
```
The original name includes its extension (`.raw`/`.d`) so the source is unambiguous. A file is written only for an MS level with at least one row; producers MUST NOT write zero-row files. A run without MSn spectra therefore has no `.msn-trace.parquet`, and a run without MS1 spectra has no `.ms1-trace.parquet`.

**Compression:** All column chunks MUST be Snappy-compressed.

## 4. Column index
Normative descriptions, logical types, and units for all columns live in §5. This is a name index only:

- `scan_id`
- `retention_time_sec`
- `ms_level`
- `total_ion_current`
- `base_peak_intensity`
- `faims_cv`
- `injection_time_ms`

reserved but not implemented:

- `base_peak_mz`
- `polarity`
- `precursor_mz`
- `isolation_window_lower_mz`
- `isolation_window_upper_mz`

## 5. Column contract
Logical types are fixed; bit width is an implementation detail governed by `precision_mode` (§8, recorded in metadata §9) **except** where a fixed width is stated in §5.2/§5.3/§8. Read through Arrow/pandas; never hard-code a byte width.

**Row ordering:** rows MUST be ordered by non-decreasing `retention_time_sec`; ties broken by ascending `scan_id`.

**`scan_id` uniqueness:** `scan_id` MUST be unique within a file.

**No other columns:** A v1 file contains only the columns defined in §5.1 and §5.2. Reserved columns (§5.3), out-of-scope columns (§5.4) and any other columns MUST NOT be written. Consumers MAY reject files that contain them.

### 5.1 Required columns (non-null in every row)
| name | logical type | unit | files | description |
|---|---|---|---|---|
| `scan_id` | integer | - | ms1, msn | Per-row id; vendor/level semantics in §7. |
| `retention_time_sec` | float | seconds | ms1, msn | Retention time as reported by the vendor, relative to the run start as the vendor defines it (Thermo: scan start time; Bruker: `Frames.Time`). Not re-zeroed to the first spectrum. |
| `ms_level` | integer | - | ms1, msn | Always `1` in MS1 file; real level in MSn file. |

### 5.2 Standard optional columns
A column may be **entirely omitted** if not attempted. Column present = "attempted for this run"; null cell = "extraction failed for this row." Never conflate; never substitute `0`.

| name | logical type | unit | notes |
|---|---|---|---|
| `total_ion_current` | float | intensity | Genuine per-spectrum TIC for both vendors. Bruker MSn caveat: §7. |
| `base_peak_intensity` | float | intensity | Genuine per-frame value for both vendors: Thermo reads it from the native scan trailer; Bruker reads `Frames.MaxIntensity`. Same aggregation caveats as `total_ion_current` (§7), no additional derivation caveats beyond those. |
| `faims_cv` | float | volts | Thermo-only. Omitted (not all-null) when FAIMS unused. Bruker must not populate this (§7). Always 32-bit (§8). |
| `injection_time_ms` | float | milliseconds | Thermo: trailer-extra value (verify label per firmware). Bruker: `Frames.AccumulationTime`. Always 32-bit (§8). |

### 5.3 Reserved columns (not implemented in v1)
Pre-standardized names/types so implementations don't diverge later. All m/z columns are **always 64-bit** (see §8).

| name | logical type | unit | file | notes |
|---|---|---|---|---|
| `base_peak_mz` | float (64-bit always) | m/z | ms1, msn | Full precision even in `low` mode, see §8. |
| `polarity` | integer (`+1`/`-1`; `null`=unknown) | - | ms1, msn | |
| `precursor_mz` | float (64-bit always) | m/z | msn | Bruker: needs `analysis.tdf_bin` decoder (§7). |
| `isolation_window_lower_mz` / `_upper_mz` | float (64-bit always) | m/z | msn | Same Bruker caveat. |

### 5.4 Currently out of scope
These columns are not planned and their names are not reserved. Adding any of them requires a new schema version, and these open questions must be settled first:

| name | open question |
|---|---|
| `charge_state` | How to encode an unknown charge (Thermo reports `0`). |
| `collision_energy` | The unit: Bruker reports eV, Thermo usually normalized collision energy (%). |
| `activation_type` | A controlled vocabulary of activation types. |

## 6. Consumer contract
- Check column presence before reading any optional/reserved column.
- A null in a present column = extraction failed for that row; never `0`, never "unsupported."
- Never hard-code numeric bit widths; read through Arrow/pandas.
- You may rely on RT ordering and `scan_id` uniqueness (§5).
- Before presenting Bruker MSn intensities, check `row_granularity` (§7).

## 7. Vendor / row-granularity semantics
**Terminology note:** Bruker's own database schema uses "Scan" to mean one ion-mobility (TIMS) sub-measurement inside a Frame (`Frames.NumScans`, typically several hundred per frame). This is unrelated to this document's `scan_id` column, which for Bruker rows always equals `Frames.Id`, i.e. it identifies a Frame, not one of these internal TIMS scans. Don't conflate the two "scan" usages.

**Thermo (all levels):** `scan_id` = native scan number, globally continuous. One row = one spectrum; TIC and base peak are genuine per-spectrum values, read directly from the native scan trailer, no aggregation of any kind.

**Bruker MS1:** `scan_id` = `Frames.Id`; one frame = one conventional (ion-mobility-collapsed) MS1 spectrum. Both `total_ion_current` (`Frames.SummedIntensities`) and `base_peak_intensity` (`Frames.MaxIntensity`) are native per-frame values, computed by Bruker's own acquisition software as the sum/max across that frame's internal TIMS mobility scans. This collapse is expected and benign: it's the same operation any non-IMS instrument performs implicitly to produce one full-range scan per RT point, and it does not mix together separate logical spectra. `row_granularity="spectrum"`.

**Bruker MSn:** `scan_id` = `Frames.Id`, but a PASEF/diaPASEF frame additionally bundles several *distinct precursor isolation events* into one pre-summed record, on top of the same mobility collapse described above for MS1. Both `total_ion_current` and `base_peak_intensity` are still read from the same native per-frame columns (`SummedIntensities` / `MaxIntensity`), but both are therefore multiplexed sums/maxima across all precursor windows in that frame, not values for any single precursor. This precursor-mixing is what `row_granularity="frame-aggregate"` flags. True per-precursor values live in `analysis.tdf_bin` and require a dedicated decoder (`timsdata`/`opentims`/`alphatims`); per-spectrum MS2 rows are out of scope for now.

| metadata key | values | meaning |
|---|---|---|
| `row_granularity` | `"spectrum"` / `"frame-aggregate"` | `"spectrum"`: Thermo any level, Bruker MS1. `"frame-aggregate"`: Bruker MSn (currently always). |

Consumers needing per-spectrum MS2 for Bruker must treat `"frame-aggregate"` as a hard capability limit.

## 8. Precision modes
`precision_mode` governs exactly three columns: `total_ion_current`, `base_peak_intensity`, `retention_time_sec`.
- **`low`** (default): 32-bit floats. Adequate for chromatogram plotting; `retention_time_sec` is accurate to a few ms even for multi-hour runs, which is sufficient for display.
- **`high`**: 64-bit floats.

Fixed-width regardless of mode: `faims_cv`, `injection_time_ms` are **always 32-bit**; all m/z columns (`base_peak_mz`, `precursor_mz`, `isolation_window_lower_mz`, `isolation_window_upper_mz`) are **always 64-bit**. Consumers still must not hard-code widths beyond these fixed cases.

## 9. File-level metadata (Parquet key-value footer)
**Required:** `schema_version`, `vendor`, `ms_level_file`, `precision_mode`, `row_granularity`, `source_filename`.

**Recommended:** `source_id`, `generator`, `extracted_at`, `acquisition_start_time`, `acquisition_path`.

| key | example | purpose |
|---|---|---|
| `schema_version` | `"1"` | Spec version. |
| `vendor` | `"thermo"`/`"bruker"` | Instrument family. |
| `ms_level_file` | `"ms1"`/`"msn"` | Which sibling this is (blind open). |
| `precision_mode` | `"low"`/`"high"` | §8. |
| `row_granularity` | `"spectrum"`/`"frame-aggregate"` | §7. Always `"spectrum"` in MS1 file. |
| `source_filename` | `"sample.raw"` or `"sample.d"` | Original source filename, including its extension. |
| `source_id` | `"a_unique_id235124"` | Stable run identifier as a string when available: Thermo, for example serial number combined with RAW `CreationDate`; Bruker `AnalysisId`. The key is omitted if no identifier is available. |
| `acquisition_path` | `"D:\\Data\\Acquisitions"` | Folder recorded by vendor metadata where the original file was acquired, not its current location. |
| `acquisition_start_time` | `"2026-07-31T12:34:56Z"` or `"2026-07-31T12:34:56"` | Acquisition start from **vendor metadata** (not filesystem), ISO-8601 without fractional seconds. Ends with `Z` (UTC) when the vendor records an absolute time (Bruker). Has no time zone suffix when the vendor records only the local clock time of the acquisition computer (Thermo); such a value is in an unknown time zone and must not be read as UTC. |
| `generator` | `"ThermoScanHeaderExtractor/2.1.0"` | Provenance. |
| `extracted_at` | `"2026-07-31T12:34:56Z"` | Extraction time (ISO-8601 UTC). |

## 10. Versioning
The document version and the schema version are recorded in the front matter of this document. The major part of the document version is the schema version. A new major version changes what a conforming file is and comes with a new `schema_version`. A minor version only clarifies or corrects this document and never changes which files conform.
