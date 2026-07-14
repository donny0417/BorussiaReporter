# Design Specification: Borussia Mönchengladbach Crawler Improvements

This document outlines the design for upgrading the BorussiaReporter service to support authenticated content access, preservation of original article layout, and extraction of inline images and videos into Naver Cafe posts.

## 1. Goal & Requirements

- **Authenticated Content Access**: Support access to membership/exclusive news content by logging into `https://account.borussia.de/`.
  - Use ID/PW from environment variables/secrets (`BORUSSIA_USERNAME`, `BORUSSIA_PASSWORD`).
  - Cache session cookies/state in `auth_state.json` to bypass login on subsequent runs, avoiding security blocks and CAPTCHA.
  - Automatically persist the updated `auth_state.json` session back to the GitHub repository via GitHub Actions.
- **Preservation of Original Layout**: Transition from plain text innerText parsing to template HTML parsing. The final Naver Cafe post should retain the same paragraph spacing, lists, headers, and relative positions of images and videos.
- **Preservation of Inline Images**: Extract all embedded images inside the article, download them locally, upload them as multiple attachments via Naver Cafe API, and insert them at their exact relative positions using `<img src="image[n]">` tags in the HTML body.
- **Inline Video Links**: Detect embedded videos (YouTube, Vimeo, FohlenTV) and place formatted video links (e.g., `📺 관련 동영상 보기`) in their exact original spots.

---

## 2. Component Design & Changes

### A. Configuration (`config.py`)
Introduce new configuration variables for credentials and session file paths:
- `BORUSSIA_USERNAME` (sourced from environment)
- `BORUSSIA_PASSWORD` (sourced from environment)
- `BORUSSIA_SESSION_PATH` (defaults to `auth_state.json` in the project root directory)

### B. Crawler & Selector Logic (`crawler.py`)
- **Login Session Logic**:
  - Start Playwright with `storage_state=BORUSSIA_SESSION_PATH` if the file exists.
  - To verify login status: Navigate to news detail. If redirect to login occurs or login elements are present, perform form fill and submit.
  - Selectors:
    - Username input: `input[name="username"]`
    - Password input: `input[name="password"]`
    - Submit button: `button.btn-primary` (containing text "ANMELDEN")
  - After successful login, save state: `await context.storage_state(path=config.BORUSSIA_SESSION_PATH)`.
- **Preservation of Layout (DOM Extraction)**:
  - Locate the `<article>` tag.
  - Parse the inner HTML using BeautifulSoup.
  - Extract all `<img>` tags. Download their raw src urls to `borussia_images/` naming them with indices (e.g., `img_0.png`, `img_1.png`). Replace each `<img>` with `[IMAGE_i]` placeholder in the HTML.
  - Extract all video frames (iframes with `youtube.com`, `vimeo.com`, or links to FohlenTV). Replace with `[VIDEO_j]` placeholder and store the URL mappings.
  - The processed HTML template with placeholders is returned for translation.

### C. Translation Prompt (`translator.py`)
Update the system prompt for Gemini (`gemini-2.5-flash`) to support HTML structure translation:
- Explicitly instruct the LLM to preserve all HTML tags (e.g. `<p>`, `<h2>`, `<strong>`, `<ul>`, `<li>`) and all placeholders (e.g. `[IMAGE_i]`, `[VIDEO_j]`) exactly as they are.
- Only translate the German text content inside the HTML elements to natural, formal Korean sports news tone.

### D. Uploader & Post Reconstruction (`uploader.py`)
- Parse the translated HTML template.
- Replace `[IMAGE_i]` with `<img src="image[i]">`.
- Replace `[VIDEO_j]` with a styled HTML link block:
  `<br><a href="[URL]" target="_blank" style="text-decoration:none;"><b>📺 [관련 동영상 보기 (링크)]</b></a><br>`
- Adjust Naver Cafe API request payload:
  - Instead of uploading a single file with key `image`, construct a list of file tuples:
    `files = [('image', (os.path.basename(path), open(path, 'rb'), 'image/png')) for path in image_paths]`
  - Pass the reconstructed HTML content via the `content` parameter (URL encoded).

### E. GitHub Actions Workflow (`.github/workflows/daily_news.yml`)
- Update environment block for `Run Main Script` step:
  - Add `BORUSSIA_USERNAME: ${{ secrets.BORUSSIA_USERNAME }}`
  - Add `BORUSSIA_PASSWORD: ${{ secrets.BORUSSIA_PASSWORD }}`
- Update `Commit and Push History` step:
  - Add `auth_state.json` to be committed and pushed along with `processed_titles.txt`.
  - Ensure the git config allows pushing changes properly.

---

## 3. Verification Plan

### Automated Verification
Run the scraper and uploader in dry-run/test mode:
1. Validate login and `auth_state.json` file creation.
2. Verify HTML template generation and successful parsing of placeholders.
3. Validate that Gemini translates only the text contents and keeps placeholders intact.
4. Verify Naver Cafe API multi-file upload using a test 카페 게시판 menu ID.

### Manual Verification
- Verify the layout and position of images/videos on Naver Cafe post draft/actual upload.
