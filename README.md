# Dominican Film Data Pipeline

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Database](https://img.shields.io/badge/Database-Supabase-3ECF8E)
![OCR](https://img.shields.io/badge/OCR-Tesseract-red)
![Azure](https://img.shields.io/badge/Azure-GPT--4o--mini-0078D4)
![Scraper](https://img.shields.io/badge/Scraper-BeautifulSoup-orange)
![Records](https://img.shields.io/badge/Records-2%2C543-orange)

ETL pipeline for extracting and structuring Dominican Republic film industry data from DGCINE official documents under Law 108-10.

> **Note:** This repository is under active development. The latest code and data are available on the [`develop`](../../tree/develop) branch.

## Overview

This pipeline scrapes, processes, and stores CIPAC investment and expense validation resolutions issued by the [Dominican Film Commission (DGCINE)](https://dgcine.gob.do) between 2012 and 2026. It uses OCR, Azure GPT-4o-mini Vision, and regex-based extraction to structure data from PDF documents into a PostgreSQL database hosted on Supabase.

## Features

- **Web Scraper** — Downloads CIPAC resolution PDFs from the DGCINE website
- **OCR Extraction** — Extracts structured fields using Tesseract OCR with Azure GPT-4o-mini Vision fallback for poor quality scans
- **Data Quality** — Confidence scoring, needs_review flagging, and manual correction audit trail
- **SQLite Storage** — Local database for development and processing
- **Supabase Migration** — Migrates data to PostgreSQL on Supabase for production use
- **Incremental Updates** — `update.py` script for processing new resolutions without overwriting existing data

## Dataset

![CIPAC Resolutions by Year](/assets/cipac_resolutions_by_year_chart.png)

| Year      | Records   |
| --------- | --------- |
| 2012      | 14        |
| 2013      | 72        |
| 2014      | 99        |
| 2015      | 145       |
| 2016      | 189       |
| 2017      | 143       |
| 2018      | 233       |
| 2019      | 164       |
| 2020      | 211       |
| 2021      | 147       |
| 2022      | 201       |
| 2023      | 330       |
| 2024      | 177       |
| 2025      | 206       |
| 2026      | 212       |
| **Total** | **2,543** |

## Project Structure

```bash
dominican-film-data-pipeline/
├── database/
│ ├── db_setup.py # SQLite setup and connection
│ ├── schema.sql # SQLite schema
│ ├── schema_postgres.sql # PostgreSQL schema (Supabase)
│ └── migrate_to_supabase.py # Migration script
├── extractor/
│ └── pdf_extractor.py # OCR + field parsers + Azure Vision fallback
├── scraper/
│ └── cipac_scraper.py # DGCINE PDF scraper
├── pipeline.py # Main ETL orchestrator
├── update.py # Incremental update script
└── data/
└── raw/cipac/ # Downloaded PDFs (gitignored)
```

## Setup

### Requirements

- Python 3.11+
- Tesseract OCR
- Azure OpenAI account (for Vision fallback)
- Supabase account

### Installation

```bash
git clone https://github.com/jorgedoiany/dominican-film-data-pipeline.git
cd dominican-film-data-pipeline
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file:

```bash
AZURE_OPENAI_KEY="your-key"
AZURE_OPENAI_ENDPOINT="https://your-service.openai.azure.com/"
AZURE_OPENAI_DEPLOYMENT="gpt-4o-mini"
SUPABASE_DB_URL="postgresql://postgres:password@pooler.supabase.com:5432/postgres"
```

## Usage

### Full pipeline run

```bash
python pipeline.py 2026
python pipeline.py 2026 --force-ocr
```

`--force-ocr` re-runs OCR extraction on all PDFs for the given year, even if results
already exist. Fields set through manual review (`manually_reviewed`, `manual_note`)
are preserved across reprocessing — see [Data Quality Notes](#data-quality-notes).

### Incremental update (new resolutions only)

```bash
python update.py 2026
```

### Migrate to Supabase

```bash
python database/migrate_to_supabase.py
```

## Law 108-10 Context

**Art. 34** — Dominican productions. Local investors receive a tax credit equal to 100% of their validated investment, applicable against income tax (ISR).

**Art. 39** — Foreign productions. Producers receive a transferable tax credit of 25% of validated expenses in the Dominican Republic (minimum USD 500,000).

## Data Quality Notes

- PDF extraction uses OCR and produces a confidence score per record. Low-confidence
  extractions are flagged with `needs_review: true` and listed in the pipeline's
  extraction summary.
- Records can be corrected by hand; corrections are tracked in the `manually_reviewed`
  and `manual_note` fields, with the note recording the field changed, the source of
  the correction, and the date.
- Reprocessing a year with `--force-ocr` re-runs extraction on every PDF for that year,
  but does not discard manual corrections: `manually_reviewed` and `manual_note` are
  loaded from the existing results and carried over to the newly extracted record,
  matched by `source_file`. All other fields are recalculated normally.

## Author

**Jorge Doiany Peguero Almonte**  
GitHub: [@jorgedoiany](https://github.com/jorgedoiany)
