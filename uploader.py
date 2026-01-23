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

def upload_single_article(post_data, access_token):
    upload_url = f"https://openapi.naver.com/v1/cafe/{config.NAVER_CLUB_ID}/menu/{config.NAVER_MENU_ID}/articles"
    
    article_text = post_data['translated_text']
    image_path = post_data['image_path']
    
    lines = article_text.strip().split('\n', 1)
    raw_title = lines[0]
    raw_body = lines[1] if len(lines) > 1 else ""

    clean_title = re.sub(r'^#+\s*', '', raw_title).strip()
    subject = urllib.parse.quote(clean_title.replace('"', "'"))

    formatted_body = raw_body.replace('"', "'")
    formatted_body = re.sub(r'###\s*(.*)', r'<br><b>[ \1 ]</b>', formatted_body)
    formatted_body = formatted_body.replace('---', '<hr>')
    formatted_body = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', formatted_body)
    formatted_body = formatted_body.replace('\n', '<br>')
    content = urllib.parse.quote(formatted_body)
    
    data = {'subject': subject, 'content': content}
    headers = {'Authorization': f"Bearer {access_token}"}
    
    try:
        with open(image_path, 'rb') as f:
            files = [('image', (os.path.basename(image_path), f, 'image/png'))]
            response = requests.post(upload_url, headers=headers, data=data, files=files)
            return response.status_code == 200
    except FileNotFoundError:
        response = requests.post(upload_url, headers=headers, data=data)
        return response.status_code == 200