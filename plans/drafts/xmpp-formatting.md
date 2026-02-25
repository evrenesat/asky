Currently in the console we have rich formatting for markdown and also we support creating HTML rendered files for response responses. But on the XMPP channel the formatting support is very sparse. Some clients support some markdown to very simple level and that makes reading good output of models, rich output of models, quite an inferior experience comparing to other forms. This plan aims to improve that. So I want to use proper message styling protocol standard for simple formatting needs. And all the markdown tables we have should be converted to a code block, should be rubbed in a code block and if needed it should be formatted a bit better like. But I I hope just dropping in a code block should be enough.

High-level plan (Slixmpp sender, BeagleIM + Conversations targets)

0) Guiding constraints
	•	Primary formatting: send readable plain text that includes lightweight markup for bold, italic, code, etc, so recipients already see formatting in BeagleIM and Conversations.
	•	Tables: do fallback rendering as a monospace code block (ASCII table), because XHTML-IM does not support tables in the recommended subset.  ￼
	•	Prefer XEP-0393 Message Styling as the baseline, it is stable and recommended for client formatting of message bodies.  ￼
	•	Treat XEP-0394 Message Markup as optional, it is experimental and support is uneven.  ￼

⸻

1) Outgoing message model

Represent each message internally as:
	•	plain_body (string)
	•	styling_body (string) - usually same as plain_body, but includes XEP-0393 markup (asterisks, underscores, backticks, fenced blocks)
	•	table_blocks (0 or more) - structured table objects that can be rendered as ASCII code blocks
	•	optional_markup_spans (optional) - if you later add XEP-0394 emission

⸻

2) Formatting strategy for bold, italic, headers, code

2.1 Use XEP-0393 in the message <body>
	•	Bold, italic, strikethrough, inline code, fenced code blocks are defined as plain text conventions (XEP-0393).  ￼
	•	This matches what you observe: BeagleIM explicitly advertises “markdown formatting”, and multiple clients implement XEP-0393-style formatting for bodies.  ￼

Implementation detail:
	•	Always send one <body> containing the XEP-0393 syntax.
	•	Do not send XHTML-IM unless you have a strong reason.

2.2 Headers

There is no universal “header” element in XEP-0393. If you want headings:
	•	Render as plain text conventions that stay readable everywhere, for example:
	•	Title on its own line
	•	underline with ==== or ----
	•	or # Title if that’s already working acceptably in BeagleIM and Conversations (you already see partial Markdown support).

Keep this consistent, do not assume every client renders Markdown headings.

⸻

3) Tables strategy (your “important” requirement)

Since XHTML-IM does not support tables in the recommended subset, do this:

3.1 Render tables as ASCII inside fenced code blocks
	•	Convert each table to a fixed-width text table.
	•	Wrap it with triple backticks (XEP-0393 code block).  ￼

Example output in body:

Users | Score
----- | -----
Ada   | 12
Bob   | 9

Notes:
	•	This works even if the receiver does zero formatting, it remains readable.
	•	For best alignment, pad columns based on display width (treat wide unicode carefully if you need it).

3.2 Apply thresholds

To avoid ugly messages:
	•	If the table is small (few columns, short values), inline ASCII table is fine.
	•	If it is large, prefer sending a CSV file or a link, but your stated goal is inline, so keep it to an agent decision rule (rows, columns, max width).

⸻

4) Capability detection (optional but useful)

4.1 Use Service Discovery (XEP-0030) once per contact resource
	•	Cache per full JID resource: supported features list.

4.2 Decide based on features
	•	If recipient advertises XEP-0393, you are good (send styling in body).
	•	If you later add XEP-0394, only attach markup spans when recipient advertises it (because it is experimental).  ￼

If you skip disco entirely, your baseline still works because it is plain text.

⸻

5) Slixmpp implementation tasks (for the coding agent)
	1.	Add a “formatting renderer” module:
	•	Input: your internal message representation
	•	Output: body_text string (XEP-0393 style), with tables rendered as fenced code blocks
	2.	Add “ASCII table renderer”:
	•	Compute column widths
	•	Produce header, separator, rows
	•	Escape backticks inside cells if needed (or choose a fence length that cannot appear in content)
	3.	Integrate into send path:
	•	msg["body"] = body_text
	•	Send as normal Slixmpp message
	4.	Optional: implement disco cache for recipients, so you can later add richer behavior without refactoring.
	5.	Explicitly do not implement XEP-0071 for tables
	•	Tables are outside the XHTML-IM integration set, so it is not a reliable path.  ￼
