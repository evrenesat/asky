# Document Q&A

asky can read local files, index their content, and let you ask questions about them. All processing runs locally - your documents are not sent anywhere except to your configured LLM for the final answer.

## Supported file types

`.txt`, `.md`, `.markdown`, `.html`, `.htm`, `.json`, `.csv`, `.pdf`, `.epub`

---

## Ask about a single file

```bash
asky -r path/to/document.pdf "What are the main conclusions?"
```

The `-r` flag enables research mode. When you pass a file path, asky reads and indexes the file before querying the model. On first use with a large file (a long PDF or EPUB), indexing can take 30-60 seconds.

![Reading and querying a document](../assets/shots/document-qa-read.gif)
<!-- vhs assets/shots/document-qa-read.tape -->

---

## Ask about a folder of documents

```bash
asky -r path/to/my-docs/ "Summarize the key points across all documents"
```

asky discovers all supported files in the directory and indexes them. Subdirectories are included.

---

## Set up a persistent document root

Instead of typing full paths every time, you can configure one or more root directories in `~/.config/asky/general.toml`:

```toml
[research]
local_document_roots = ["/Users/you/Documents", "/Users/you/work-docs"]
```

After this, you can reference files by path relative to any root:

```bash
asky -r reports/q4-review.pdf "What were the revenue figures?"
asky -r contracts/ "Do any contracts mention penalty clauses?"
```

---

## Continue a conversation about a document

Use a sticky session to keep the document context across multiple questions:

```bash
asky -r report.pdf -ss "Q4 Review" "What does section 3 say about costs?"
```

In later terminal sessions, resume the same conversation:

```bash
asky -rs "Q4 Review" "How does that compare to Q3?"
```

The document corpus is stored with the session - you don't need to pass `-r report.pdf` again on follow-up turns.

---

## Browse a document by section

For books and structured documents, you can list and summarize sections without running a full research query.

List all sections:

```bash
asky -r mybook.epub --summarize-section
```

![Listing document sections](../assets/shots/document-qa-sections.gif)
<!-- vhs assets/shots/document-qa-sections.tape -->

Summarize a specific section by title:

```bash
asky -r mybook.epub --summarize-section "Chapter 3"
```

Summarize a specific section by exact section ID:

```bash
asky -r mybook.epub --summarize-section --section-id section-001
```

Important: `--summarize-section section-001` treats `section-001` as a title query, not an
ID. For deterministic ID selection, always pass `--section-id`.

Three detail levels are available:

```bash
asky -r mybook.epub --summarize-section "Chapter 3" --section-detail compact
asky -r mybook.epub --summarize-section "Chapter 3" --section-detail balanced   # default
asky -r mybook.epub --summarize-section "Chapter 3" --section-detail max
```

---

## Test retrieval before querying

If you want to verify that your document is indexed and that a particular topic is retrievable, run a retrieval test without invoking the LLM:

```bash
asky -r mybook.epub --query-corpus "your search phrase"
```

This shows which chunks were retrieved and their relevance scores. Useful for debugging when the LLM seems to be ignoring document content.

---

## Receive documents over XMPP

If you are running daemon mode, you can send a file attachment from any XMPP client. asky will index it automatically and respond to questions about it in the same conversation thread.

See [XMPP Daemon Mode](./xmpp_daemon.md) for setup.

---

## Notes

- The first query against a new document is slower due to indexing. Subsequent queries reuse the cached index.
- If you update a file on disk, re-run with `-r path/to/file` to reindex.
- Local files are referenced internally by safe handles (`corpus://cache/<id>`) - raw filesystem paths are not exposed to the model.
