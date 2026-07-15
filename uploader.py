import requests
import urllib.parse
import re
import os
import mimetypes
import config

def get_naver_access_token():
    token_url = "https://nid.naver.com/oauth2.0/token"
    params = {
        "grant_type": "refresh_token",
        "client_id": config.NAVER_CLIENT_ID,
        "client_secret": config.NAVER_CLIENT_SECRET,
        "refresh_token": config.NAVER_REFRESH_TOKEN
    }
    res = requests.get(token_url, params=params).json()
    return res.get("access_token")

def _download_image(url):
    # 네이버 카페 글쓰기 API는 본문 HTML 안에 외부 도메인 <img src="..."> 태그를 넣으면
    # 처리에 실패한다(HTTP 403, 에러코드 999). 그래서 URL 이미지도 다운로드해서
    # 기존에 잘 동작하는 멀티파트 첨부 방식으로 올린다.
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()
        ext = mimetypes.guess_extension(content_type) or '.jpg'
        filename = f"dl_{abs(hash(url))}{ext}"
        path = os.path.join(config.IMAGE_DIR, filename)
        with open(path, 'wb') as f:
            f.write(resp.content)
        return path
    except Exception:
        return None

def _replace_media_markers(formatted_body, images, videos):
    # 이미지는 본문 내 정확한 위치 삽입이 보장되지 않으므로, 마커는 본문에서 지우고
    # 멀티파트 첨부 목록에 순서대로 추가해서 함께 올린다.
    attachments = []

    for img in images:
        marker_tag = f"[[{img['marker']}]]"
        formatted_body = formatted_body.replace(marker_tag, '')

        if img.get('url'):
            downloaded = _download_image(img['url'])
            if downloaded:
                attachments.append(downloaded)
        elif img.get('fallback_screenshot'):
            attachments.append(img['fallback_screenshot'])

    for vid in videos:
        marker_tag = f"[[{vid['marker']}]]"
        replacement = f'🎥 관련 영상: <a href="{vid["url"]}">{vid["url"]}</a>'
        formatted_body = formatted_body.replace(marker_tag, replacement)

    return formatted_body, attachments

def upload_single_article(post_data, access_token):
    upload_url = f"https://openapi.naver.com/v1/cafe/{config.NAVER_CLUB_ID}/menu/{config.NAVER_MENU_ID}/articles"

    article_text = post_data['translated_text']
    image_path = post_data['image_path']
    images = post_data.get('images', [])
    videos = post_data.get('videos', [])

    lines = article_text.strip().split('\n', 1)
    raw_title = lines[0]
    raw_body = lines[1] if len(lines) > 1 else ""

    clean_title = re.sub(r'^#+\s*', '', raw_title).strip()
    subject = urllib.parse.quote(clean_title.replace('"', "'"))

    formatted_body = raw_body.replace('"', "'")
    formatted_body = re.sub(r'(^|\n)-\s+(.*)', r'\1&nbsp;&nbsp;• \2', formatted_body)
    formatted_body = re.sub(r'###\s*(.*)', r'<br><b>[ \1 ]</b>', formatted_body)
    formatted_body = formatted_body.replace('---', '<hr>')
    formatted_body = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', formatted_body)
    formatted_body, fallback_attachments = _replace_media_markers(formatted_body, images, videos)
    formatted_body = formatted_body.replace('\n', '<br>')
    content = urllib.parse.quote(formatted_body)

    data = {'subject': subject, 'content': content}
    headers = {'Authorization': f"Bearer {access_token}"}

    attachment_paths = [image_path] + fallback_attachments
    opened_files = []
    try:
        files = []
        for path in attachment_paths:
            try:
                f = open(path, 'rb')
            except FileNotFoundError:
                continue
            opened_files.append(f)
            mime_type = mimetypes.guess_type(path)[0] or 'image/png'
            files.append(('image', (os.path.basename(path), f, mime_type)))

        response = requests.post(upload_url, headers=headers, data=data, files=files or None)
        if response.status_code != 200:
            print(f"      ⚠️ 업로드 실패 응답 ({response.status_code}): {response.text[:500]}")
        return response.status_code == 200
    finally:
        for f in opened_files:
            f.close()
