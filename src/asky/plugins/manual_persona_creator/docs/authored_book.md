+++
title = "Authored Books"
summary = "Ingest long-form books with high-fidelity viewpoint extraction."
+++

# Authored Books

Authored books are primary sources that provide the foundation for a persona's worldview.

## Supported Content
Use this for PDFs, EPUBs, or plain text files that represent a single coherent work by an author.

## Server-Local Paths
Ingestion requires a path to a file that is accessible by the server. 

## Ingestion Pipeline
1. **Preflight**: The system looks up metadata (title, author, ISBN) and identifies extraction targets.
2. **Metadata Confirmation**: You confirm the metadata and the specific viewpoints or claims to extract.
3. **Extraction**: A multi-pass job extracts structured viewpoints with supporting evidence.
4. **Materialization**: The extracted knowledge is projected into the persona's catalog.

## Identity and Duplicates
The `book_key` (derived from title, year, and ISBN) prevents duplicate ingestion. If a job is interrupted, it can be resumed using its job ID.
