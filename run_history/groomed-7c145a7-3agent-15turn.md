# Summary

The team is building a command-line bookmark manager that allows users to save, organize, search, and manage URL bookmarks in a plain-text format. The tool emphasizes fast capture, local storage, data ownership, and integration into terminal workflows. It stores bookmarks in TSV format with support for URLs, dates, tags, and optional titles.

# Agreed Requirements

## Core Functionality
- **Three primary commands**: `add`, `list`, `delete`
- Users can add bookmarks with URL (required), tags (optional), and title (optional)
- Users can list all bookmarks or filter by tags
- Users can search bookmarks using text/regex matching via `list --search`
- Users can delete bookmarks using pattern matching with confirmation prompts
- Duplicate URLs are allowed with a warning (suppressible via `--quiet` flag)

## Data Storage
- Plain-text TSV format with four columns: URL, Date (ISO 8601), Tags (comma-separated), Title (optional)
- File stored at `~/.bookmarks` by default
- Multiple bookmark files supported via `BOOKMARK_FILE` environment variable or `--file` flag
- Files are version-controllable and manually editable
- Standard TSV escaping for tabs (`\t`), newlines (`\n`), and backslashes (`\\`) in titles

## Organization
- Tags are the primary organizational method (no folder hierarchy)
- Tag names restricted to alphanumeric characters, underscores, and hyphens (`^[a-zA-Z0-9_-]+$`)
- No custom/extensible fields in MVP

## Technical Constraints
- Single-user, local-first tool (no authentication, no cloud sync)
- No external dependencies for core operations (offline-first)
- Fast bookmark capture (under 1 second for add operation)
- Human-readable and editable data format
- Title display shows truncated URL when title is missing

## Error Handling
- Invalid lines in bookmark file show warnings but don't block operations
- Nonexistent tag searches return empty results (no error)
- Missing bookmark file shows helpful message suggesting first bookmark addition
- Pattern matching with no results shows appropriate message with non-zero exit

# Open Questions

## Date Filtering (Deferred to Planning)
- Whether to include `--after DATE` and `--before DATE` flags for filtering bookmarks by date range
- Decision deferred based on implementation effort assessment
- If included, format will be ISO 8601 dates only (no relative dates)

## Delete Command Pattern Matching Details
- Exact behavior of pattern matching (substring vs. regex)
- Confirmation prompt UX when multiple bookmarks match

# Assumptions

- URLs do not contain tab characters
- Most bookmark titles do not contain pipe or tab characters (escaping is edge case)
- Users are comfortable with command-line interfaces and basic Unix tools
- Users want data ownership and portability over convenience features
- Fast capture is more important than complete metadata at save time
- Users can manually edit TSV files when needed
- Browser integration and sync are not required
- The tool targets developers who live in terminal environments

# Out of Scope

## Explicitly Excluded from MVP
- Auto-fetching titles during bookmark save (can be added as separate command post-MVP)
- Browser extensions or integration
- Cloud synchronization or multi-device sync
- Web scraping or link validation
- Auto-categorization or ML-powered features
- Fuzzy search built into the tool (users can pipe to `fzf`)
- Rich text descriptions or WYSIWYG editing
- Custom/extensible metadata fields
- Folder-based organization or hierarchies
- Import/export functionality (beyond manual file management)
- Edit command for modifying existing bookmarks (manual file editing for MVP)
- Relative date parsing ("1 week ago")
- Natural language date queries

## Implementation Details (Not Product Decisions)
- Specific parsing libraries or tools
- Database engine choices
- Performance optimization strategies
- Detailed error message wording (beyond general behavior)
