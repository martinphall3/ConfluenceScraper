# CLIENTHELP Confluence Knowledge Base Exporter

`export_clienthelp_combined.py` exports every eligible page from a Confluence Cloud space into a single searchable knowledge-base package. It preserves the page hierarchy, downloads image attachments, converts page content to Markdown and HTML, optionally extracts text from screenshots with OCR, includes attachments and comments, and can render a PDF.

## Outputs

By default, the script creates:

```text
export/
├── assets/                 # Downloaded images
├── export_result.md        # Combined Markdown knowledge base
├── export_result.html      # Combined HTML knowledge base
└── export_result.pdf       # PDF generated from the HTML, when WeasyPrint is available
```

Each exported page includes its title, source link, ancestor path, labels, last-updated date, page body, attachments, and optionally comments. Links to other exported Confluence pages become in-document links in the HTML and PDF outputs.

## Requirements

- Python 3.9 or later
- Access to the target Confluence Cloud space
- A Confluence account email address
- An Atlassian API token
- Python packages:
  - `requests`
  - `beautifulsoup4`
  - `markdownify`
  - `Pillow` and `pytesseract` for optional OCR
  - `weasyprint` for optional PDF creation
- The Tesseract executable is also required when OCR is enabled.

Install the Python dependencies:

```bash
python -m pip install requests beautifulsoup4 markdownify Pillow pytesseract weasyprint
```

> WeasyPrint and Tesseract may require additional operating-system packages. If WeasyPrint is unavailable, the script still generates Markdown and HTML and prints instructions for saving the HTML as a PDF from Chrome.

## Configuration

Open `export_clienthelp_combined.py` and set the values in the **settings** section:

```python
SITE = "https://your-domain.atlassian.net"
EMAIL = "your-email@example.com"
TOKEN = "your-atlassian-api-token"
SPACE = "CLIENTHELP"
HOME_ID = "123456789"
OUT = "export"
BASENAME = "export_result"
EXCLUDE_LABEL = "exclude-bot"
INCLUDE_COMMENTS = True
```

| Setting | Purpose |
|---|---|
| `SITE` | Confluence Cloud base URL, without a trailing `/wiki` |
| `EMAIL` | Email address associated with the Atlassian account |
| `TOKEN` | Atlassian API token used for HTTP Basic authentication |
| `SPACE` | Confluence space key to export |
| `HOME_ID` | Homepage content ID; places the homepage first when it is a root page |
| `OUT` | Output directory |
| `BASENAME` | Base filename used for Markdown, HTML, and PDF outputs |
| `EXCLUDE_LABEL` | Pages carrying this label are omitted by the CQL query |
| `INCLUDE_COMMENTS` | Controls whether page comments are included |

### Keep credentials out of source control

The supplied script stores `EMAIL` and `TOKEN` directly in its settings section. Do not commit a populated token. For shared or production use, move credentials to environment variables or a secret manager, then read them with `os.environ`.

Example:

```python
EMAIL = os.environ["CONFLUENCE_EMAIL"]
TOKEN = os.environ["CONFLUENCE_API_TOKEN"]
```

## Running the exporter

From the directory containing the script:

```bash
python export_clienthelp_combined.py
```

The script will:

1. Query Confluence for pages in the configured space, excluding pages with the configured exclusion label.
2. Follow pagination until all matching pages are collected.
3. Order pages by hierarchy using a depth-first traversal, with sibling pages sorted by title.
4. Download image attachments into the `assets` directory.
5. rewrite page images and links for the local combined output.
6. Convert each page to Markdown and HTML.
7. Add page metadata, attachment links, and comments.
8. Write the combined Markdown and HTML files.
9. Generate a PDF from the HTML if WeasyPrint is available.

## OCR controls

OCR is enabled by default when both `pytesseract` and Pillow can be imported. Disable it for a run by setting `OCR=0`.

macOS or Linux:

```bash
OCR=0 python export_clienthelp_combined.py
```

PowerShell:

```powershell
$env:OCR = "0"
python export_clienthelp_combined.py
```

When OCR is enabled, text recognized in downloaded screenshots is inserted below the corresponding image with a `[Screenshot text]` prefix.

## Export behavior

### Included content

- Pages returned by the configured CQL query
- Page hierarchy and ancestor breadcrumb
- Labels and last-updated date
- Export-view page content
- Image attachments stored locally
- Links to non-image attachments
- Comments, when `INCLUDE_COMMENTS` is `True`
- OCR text from screenshots, when OCR is enabled

### Excluded or unchanged content

- Pages labeled with `EXCLUDE_LABEL`
- Confluence icon and emoticon images
- External images, which remain linked to their original URLs
- PDF output when WeasyPrint cannot be imported

## Authentication and permissions

The exporter uses a persistent `requests.Session` with the configured email and API token. The account must be able to view the space, pages, comments, and attachments being exported. If Confluence returns an HTML login or error page instead of image data, the script rejects it rather than saving it as an image.

## Troubleshooting

### `401 Unauthorized` or `403 Forbidden`

- Verify `SITE`, `EMAIL`, and `TOKEN`.
- Confirm that the API token belongs to the configured email address.
- Confirm that the account can access the target space and restricted pages.

### No pages are exported

- Confirm the `SPACE` value is the space key, not the display name.
- Check whether the exclusion label removes the expected pages.
- Confirm that the account can search the space through the Confluence REST API.

### Images are missing

- Review console messages beginning with `IMAGE ERROR` or `WARNING`.
- Confirm that the account can download the attachment.
- Confirm the output directory is writable.
- Check whether the source image is external; external images are not downloaded.

### PDF is skipped

If WeasyPrint cannot be imported, open `export/export_result.html` in Chrome and use **Print > Save as PDF**. For automated PDF generation, install WeasyPrint and its required operating-system libraries.

### OCR does not run

- Install both `Pillow` and `pytesseract`.
- Install the Tesseract executable and make sure it is available on the system path.
- Confirm that the `OCR` environment variable is not set to `0`.

### Rate limits or temporary server errors

The `get()` helper retries HTTP `429` and `5xx` responses up to six times. It honors the `Retry-After` header when present and otherwise waits 10 seconds between attempts.

## Known implementation considerations

- The script requests up to 100 comments or attachments per API call in some functions. `download_page_images()` handles attachment pagination, while `comments()` and `attachments()` do not currently paginate beyond their first response.
- Credentials are configured directly in the script unless you replace them with environment variables.
- The output directory is reused. Existing files with the same names may be overwritten, and stale assets are not automatically removed.
- The PDF stylesheet targets US Letter paper and uses Helvetica/Arial-family fonts.
- The exporter prints progress and errors to standard output; it does not currently create a structured log file.

## Suggested `.gitignore`

```gitignore
# Exported knowledge-base content
export/

# Local credentials and environment files
.env

# Python cache
__pycache__/
*.py[cod]
```

## Security notes

- Treat the generated files as potentially sensitive because they may contain restricted page content, comments, attachment links, and OCR text.
- Store the API token in an environment variable or approved secret manager.
- Restrict access to the export directory according to the source space's data classification and sharing rules.
- Review generated output before using it as a chatbot or retrieval knowledge source, especially because comments may contain corrections or informal content.

## License

No license is included with the script. Add an appropriate license or internal-use notice before distributing it outside the organization.
