# Web Admin Console

The asky Web Admin Console provides a browser-based interface for managing personas, reviewing web collections, and monitoring background jobs.

## 1. Access and Authentication

The console is hosted by the `gui_server` plugin and is available only when the asky daemon is running.

- **Default URL**: `http://127.0.0.1:8766/`
- **Authentication**: Requires a password configured in `plugins/gui_server.toml` or set via the `ASKY_GUI_PASSWORD` environment variable.

If no password is set, the GUI server will refuse to start for security reasons.

## 2. Navigation

- **Dashboard**: Overview of registered plugins and quick links.
- **Personas**: Manage your knowledge personas.
- **Sessions**: Bind personas to specific chat sessions.
- **Jobs**: Monitor background ingestion and collection tasks.
- **General**: Edit daemon and model configuration.

## 3. Persona Management

The Personas page allows you to view the knowledge base of each persona.

- **Authored Books**: List and add long-form sources (PDF, EPUB).
- **Knowledge Sources**: Review and manage individual articles, interviews, and other short-form content.
- **Web Collections**: Review results from guided web scraping.

### 3.1 Background Ingestion

When you add a book or a source via the web console, a background job is created. You can monitor the progress on the **Jobs** page. This ensures the browser remains responsive even during heavy LLM-driven extraction tasks.

## 4. Web Collection Review

Milestone 4 introduced guided web scraping. The web console provides the primary interface for reviewing these results:

1.  Navigate to a persona's **Web Collections** tab.
2.  Click **Review** on a collection.
3.  For each page, you can see the LLM-extracted preview (viewpoints, facts) and the original content.
4.  **Approve** the page to project it into the persona's permanent knowledge, or **Reject** it to discard.

## 5. Session Binding

The **Sessions** page allows you to persistently bind a persona to a session. Once bound, all queries in that session will automatically use the persona's knowledge and grounded answering rules without needing to use the `@mention` syntax every time.
