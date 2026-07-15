import requests
import urllib.parse
import re
import os
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

def _replace_media_markers(formatted_body, images, videos):
    # 인라인 배치 가능한 이미지(URL)는 <img> 태그로 직접 삽입.
    # URL 추출에 실패해 스크린샷으로 대체된 이미지는 본문 내 정확한 위치 삽입이 보장되지 않으므로,
    # 마커는 지우고 멀티파트 첨부 목록에 추가해서 함께 올린다.
    attachments = []

    for img in images:
        marker_tag = f"[[{img['marker']}]]"
        if img.get('url'):
            replacement = f'<img src="{img["url"]}">'
            formatted_body = formatted_body.replace(marker_tag, replacement)
        elif img.get('fallback_screenshot'):
            formatted_body = formatted_body.replace(marker_tag, '')
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
            files.append(('image', (os.path.basename(path), f, 'image/png')))

        response = requests.post(upload_url, headers=headers, data=data, files=files or None)
        if response.status_code != 200:
            print(f"      ⚠️ 업로드 실패 응답 ({response.status_code}): {response.text[:500]}")
        return response.status_code == 200
    finally:
        for f in opened_files:
            f.close()
