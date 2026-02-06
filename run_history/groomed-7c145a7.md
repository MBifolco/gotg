# Scope Summary: Command-Line Bookmark Manager

## Summary

The team is building a command-line bookmark manager (v1) that allows users to save URLs with metadata, organize them using tags, search/filter bookmarks, and manage tags globally. The tool emphasizes simplicity with a clear data model where URLs serve as unique identifiers, tags provide flexible organization, and all operations use explicit CLI commands with flags.

## Agreed Requirements

### Core Functionality
1. **Add bookmarks** with required URL and title, optional description and tags via command: `bookmark add <url> --title="..." [--desc="..."] [--tag=X] [--tag=Y]`
2. **List bookmarks** with filtering and sorting: `bookmark list [--tag=X] [--sort=date|alpha]` (default sort: date added, newest first)
3. **Search bookmarks** by text substring across title/URL/description: `bookmark search <text> [--tag=X]`
4. **Edit bookmarks** by ID - title and description only (URLs cannot be edited)
5. **Tag management** with separate commands:
   - `bookmark add-tag <id> <tag>` - add single tag to bookmark
   - `bookmark remove-tag <id> <tag>` - remove single tag from bookmark
6. **Delete bookmarks** by ID: `bookmark delete <id>`
7. **List all tags** currently in use: `bookmark tags`
8. **Rename tags globally** with merge behavior if target tag exists
9. **Remove tag from all bookmarks** with confirmation prompt showing count affected
10. **Export bookmarks** to file (format TBD - JSON, CSV, or plain text)

### Data Model & Constraints
- **URLs are unique keys** - cannot have duplicate URLs; attempting to add existing URL should show informative message directing user to edit existing bookmark
- **Tags are case-insensitive** - normalized to lowercase for storage and display
- **Auto-generated metadata**: short integer ID, date added, date modified (not user-editable)
- **Required fields**: URL, title
- **Optional fields**: description, tags
- **Multiple tags per bookmark** are allowed
- **Tag filtering uses OR logic** when multiple tags specified
- **Search uses case-insensitive substring matching**

### User Experience
- Separate commands for browsing (`list`) vs finding (`search`) based on user intent
- Consistent output format between list and search results
- Short integer IDs displayed in list view for easy reference in edit/delete operations
- Full bookmark details shown in list output (not abbreviated)

## Open Questions

1. **Tag editing compromise**: Should there be a `bookmark set-tags <id> --tags=X,Y,Z` command for full tag replacement, or are add-tag/remove-tag sufficient?

2. **Shorthand flags**: Should the tool support shorthand flags (`-t` for `--title`, `-d` for `--desc`, `-g` for `--tag`) to reduce typing?

3. **Description length**: Should descriptions be limited in length (e.g., 200 chars max), or allow arbitrary length and accept verbose list output?

4. **Multiple tags in search**: When using `bookmark search "text" --tag=python --tag=tutorial`, should this be OR logic (python OR tutorial) or AND logic (must have both)?

5. **Export format**: What format(s) should export support - JSON, CSV, plain text, or multiple formats with a flag?

6. **Command name**: Is `bookmark` the final command name, or should it be `bm`, `bookmarks`, or something else?

7. **Date filtering**: Should users be able to filter by date range in v1, or defer this to future versions?

8. **Empty state handling**: What specific messages should appear when:
   - No bookmarks exist and user runs `bookmark list`
   - Search returns no results
   - User tries to edit/delete non-existent ID

9. **Tag lifecycle**: When a tag is removed from all bookmarks, should it automatically disappear from `bookmark tags` list, or is explicit "delete tag" command needed?

## Assumptions

- Users will have **dozens to a few hundred bookmarks** (typical case), with power users potentially reaching 1000+
- Simple substring search will be sufficient at this scale; ranking/relevance scoring not needed
- Users can manually add their initial bookmarks (no immediate need for browser import)
- URLs going down temporarily is acceptable (no need for alive checking)
- Fetching page titles automatically from URLs is too complex for v1
- Users know what they're bookmarking and can provide titles
- List output showing full details is acceptable even if verbose
- Tags only exist when bookmarks use them (no standalone tag management needed)
- When renaming tag "js" to "javascript" where "javascript" already exists, merging is the intended behavior

## Out of Scope

Explicitly deferred to future versions or excluded:

1. **Import from browsers** - users will add bookmarks manually in v1
2. **Bulk operations** - no batch delete, retag, or other multi-bookmark operations
3. **Interactive mode** - single commands only, no interactive CLI session
4. **URL alive checking** - no validation that URLs are still accessible
5. **Boolean search operators** - no AND, OR, NOT operators in search
6. **Folders/hierarchies** - tags only for organization
7. **Relevance ranking** - search results shown in date order
8. **Match highlighting** - no highlighting of search terms in results
9. **Full-text search engines** - simple substring matching only
10. **Ratings, categories, or other metadata** beyond title, URL, description, tags, and dates
11. **Editing URLs** - blocked since URLs are unique keys
