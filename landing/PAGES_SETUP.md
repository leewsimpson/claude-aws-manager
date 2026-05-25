# GitHub Pages Setup

The landing page auto-deploys to GitHub Pages on every push to `main` that touches `landing/`.

## 1. Enable GitHub Pages

1. Go to **Settings → Pages**
2. Under "Source", select:
   - **Deploy from branch**
   - Branch: **gh-pages**
   - Folder: **/ (root)**
3. Save

The workflow will create the `gh-pages` branch on first run.

## 2. Access

After the first deploy completes:
- **URL:** `https://leewsimpson.github.io/claude-aws-manager/`

## How it works

- `.github/workflows/deploy-pages.yml` triggers on:
  - Push to `main` + changes in `landing/` or workflow file
  - Manual dispatch (workflow_dispatch)
- Validates HTML, uploads artifact, deploys to `gh-pages`
- GitHub Pages serves the site at the repo URL

## Local preview

```bash
# Quick server
cd landing
python3 -m http.server 8000
# → http://localhost:8000
```

## Customization

Edit `deploy-pages.yml` to:
- Change trigger paths (currently `landing/**`)
- Add build steps (minify, etc.)
- Customize the HTML validation
