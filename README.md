# Dominican Film Data Pipeline

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Database](https://img.shields.io/badge/Database-Supabase-3ECF8E)
![OCR](https://img.shields.io/badge/OCR-Tesseract-red)
![Azure](https://img.shields.io/badge/Azure-GPT--4o--mini-0078D4)
![Scraper](https://img.shields.io/badge/Scraper-BeautifulSoup-orange)
![Records](https://img.shields.io/badge/Records-2%2C532-lightgrey)

ETL pipeline for extracting and structuring Dominican Republic film industry data from DGCINE official documents under Law 108-10.

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

## Author

**Jorge Doiany Peguero Almonte**  
GitHub: [@jorgedoiany](https://github.com/jorgedoiany)
