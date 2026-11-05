# Repository Media and Assets Branch

This branch is used exclusively to host media files (GIFs, images, and video demos) for the project's documentation. Keeping these large binary files on an isolated branch prevents the `main` branch from becoming bloated.

## Layout and naming

Media files are stored in `docs/screenshots/` and named `<subject>-v<N>.<ext>`, for example `report-overlay-v1.png`.

- `<subject>` is a short, lowercase, hyphen-separated description of what is shown.
- `<N>` starts at 1 and counts the versions of that subject.
- A published file is never changed. To update it, add a new file with the next version number and update the links that should show it.

## Linking to media

Link to a file with its full URL, so that it also displays outside GitHub, for example on PyPI:

```markdown
![Report overlay view](https://raw.githubusercontent.com/maxperutzlabs-ms/rawtrace-qc/media/docs/screenshots/report-overlay-v1.png)
```
